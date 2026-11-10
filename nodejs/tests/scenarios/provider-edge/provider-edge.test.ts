import { ProviderEdge, TruthPage, startProviderEdge } from '.'
import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import http from 'http'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

const TRACKING_KEYS = 'scenario-tracking-key'
const ALICE = 'run-1-1@www.example.com'
const BOB = 'run-1-2@www.example.com'

describe('provider edge', () => {
    let edge: ProviderEdge
    let ses: SESv2Client

    beforeEach(async () => {
        edge = await startProviderEdge({ port: 0, trackingKeys: TRACKING_KEYS })
        ses = new SESv2Client({
            endpoint: edge.url,
            region: 'us-east-1',
            credentials: { accessKeyId: 'edge', secretAccessKey: 'edge' },
            maxAttempts: 1,
        })
    })

    afterEach(async () => {
        ses.destroy()
        await edge.close()
    })

    const send = (to: string, trackingCode?: string): Promise<string> =>
        ses
            .send(
                new SendEmailCommand({
                    FromEmailAddress: 'flows@www.example.com',
                    Destination: { ToAddresses: [to] },
                    Content: {
                        Simple: {
                            Subject: { Data: 'Hello' },
                            Body: { Text: { Data: 'Hello there' } },
                            Headers: trackingCode ? [{ Name: 'X-PostHog-Tracking-Code', Value: trackingCode }] : [],
                        },
                    },
                })
            )
            .then(
                () => 'sent',
                (error: Error) => error.name
            )

    const sendEach = async (recipients: string[]): Promise<string[]> => {
        const outcomes: string[] = []
        for (const recipient of recipients) {
            outcomes.push(await send(recipient))
        }
        return outcomes
    }

    const call = async (method: string, path: string, body?: object): Promise<{ status: number; json: any }> => {
        const response = await internalFetch(`${edge.url}${path}`, {
            method,
            headers: { 'content-type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        })
        const text = await response.text()
        return { status: response.status, json: text ? parseJSON(text) : undefined }
    }

    const truth = async (query = ''): Promise<TruthPage> => (await call('GET', `/_truth${query}`)).json

    const addFault = async (fault: object): Promise<string> => {
        const { status, json } = await call('POST', '/_faults', fault)
        expect(status).toBe(201)
        return json.id
    }

    it('records a send with the unit id from the recipient and the action id from the signed tracking code', async () => {
        const trackingCode = new EmailTrackingCodeSigner(TRACKING_KEYS, 'https://track.example.com').generate({
            functionId: 'flow-1',
            id: 'invocation-1',
            teamId: 1,
            state: { actionId: 'email-step' },
        })

        expect(await send(ALICE, trackingCode)).toBe('sent')

        expect((await truth()).records).toEqual([
            expect.objectContaining({
                seq: 1,
                kind: 'ses.send',
                status: 200,
                unitId: 'run-1-1',
                actionId: 'email-step',
            }),
        ])
    })

    it('leaves tracking unknown when the edge has no configuration sets', async () => {
        await send(ALICE)

        expect((await truth()).records[0].detail.message?.tracked).toBeUndefined()
    })

    it('answers a request the edge fails on with a 500 and keeps serving', async () => {
        const { status, json } = await call('GET', '//edge:99999/')

        expect([status, json.message]).toEqual([500, expect.stringContaining('The edge failed')])
        expect((await call('GET', '/_health')).json).toEqual({ ok: true })
    })

    it('records a send whose address list is not a list as a 400', async () => {
        const { status } = await call('POST', '/v2/email/outbound-emails', {
            Destination: { ToAddresses: 'not-a-list' },
            Content: { Simple: { Subject: { Data: 'Hello' } } },
        })

        expect(status).toBe(400)
        expect((await truth()).records).toEqual([
            expect.objectContaining({ status: 400, detail: { error: 'Every address list needs to be a list.' } }),
        ])
    })

    it('keeps serving after a client aborts its upload', async () => {
        await new Promise<void>((resolve) => {
            const upload = http.request(`${edge.url}/_faults`, {
                method: 'POST',
                headers: { 'content-length': '1000' },
            })
            upload.on('error', () => resolve())
            upload.write('{"name"', () => upload.destroy())
        })

        expect((await call('GET', '/_health')).json).toEqual({ ok: true })
    })

    it('rejects startup on a port another listener holds', async () => {
        await expect(startProviderEdge({ port: Number(new URL(edge.url).port) })).rejects.toThrow('EADDRINUSE')
    })

    it('correlates and matches a recipient with a display name by its bare address', async () => {
        await addFault({
            name: 'ses.reject',
            params: { type: 'rejected' },
            match: { recipient: ALICE },
            dose: { count: 1 },
        })

        expect(await sendEach([`"Alice" <${ALICE}>`, `"Alice" <${ALICE}> (work)`])).toEqual(['MessageRejected', 'sent'])

        expect((await truth()).records.map((record) => record.unitId)).toEqual(['run-1-1', 'run-1-1'])
    })

    it('applies a share at every crossing even where the product rounds just below it', async () => {
        await addFault({ name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 0.58 } })

        const outcomes = await sendEach(Array.from({ length: 50 }, () => ALICE))

        expect(outcomes.filter((outcome) => outcome === 'MessageRejected')).toHaveLength(29)
    })

    it.each([
        ['a counted dose', { count: 2 }, ['MessageRejected', 'sent', 'MessageRejected', 'sent']],
        ['a share', { share: 0.5 }, ['sent', 'sent', 'MessageRejected', 'sent']],
    ])('rejects %s of the sends to the matched recipient', async (_name, dose, expected) => {
        await addFault({ name: 'ses.reject', params: { type: 'rejected' }, match: { recipient: ALICE }, dose })

        expect(await sendEach([ALICE, BOB, ALICE, ALICE])).toEqual(expected)
        expect((await truth()).records.map((record) => [record.unitId, record.status, record.fault])).toEqual(
            expected.map((outcome, index) => [
                index === 1 ? 'run-1-2' : 'run-1-1',
                outcome === 'sent' ? 200 : 400,
                outcome === 'sent' ? undefined : 'ses.reject',
            ])
        )
    })

    it('stops applying a fault once its time window passes', async () => {
        const start = Date.now()
        const clock = jest.spyOn(Date, 'now').mockReturnValue(start)
        try {
            await addFault({ name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 1 }, for: '30s' })
            expect(await send(ALICE)).toBe('MessageRejected')

            clock.mockReturnValue(start + 30_000)

            expect(await send(ALICE)).toBe('sent')
        } finally {
            clock.mockRestore()
        }
    })

    it('clears one fault or every fault while the truth keeps its sequence', async () => {
        const forAlice = await addFault({
            name: 'ses.reject',
            params: { type: 'rejected' },
            match: { recipient: ALICE },
            dose: { share: 1 },
        })
        await addFault({
            name: 'ses.reject',
            params: { type: 'rejected' },
            match: { recipient: BOB },
            dose: { share: 1 },
        })
        expect(await sendEach([ALICE, BOB])).toEqual(['MessageRejected', 'MessageRejected'])

        expect((await call('DELETE', `/_faults/${forAlice}`)).status).toBe(204)
        expect(await sendEach([ALICE, BOB])).toEqual(['sent', 'MessageRejected'])

        expect((await call('DELETE', '/_faults')).status).toBe(204)
        expect(await sendEach([ALICE, BOB])).toEqual(['sent', 'sent'])

        expect((await call('DELETE', `/_faults/${forAlice}`)).status).toBe(404)
        expect((await truth()).records.map((record) => record.seq)).toEqual([1, 2, 3, 4, 5, 6])
    })

    it('pages the truth after a sequence number', async () => {
        await sendEach([ALICE, BOB, ALICE])

        expect(await truth('?after=1&limit=1')).toEqual({
            records: [expect.objectContaining({ seq: 2, unitId: 'run-1-2' })],
            next: 2,
        })
        expect(await truth('?after=3')).toEqual({ records: [], next: 3 })
    })

    it.each([
        ['a fault no card can name', { name: 'ses.status', params: { status: 500 }, dose: { count: 1 } }, 'name'],
        ['a fault without a dose', { name: 'ses.reject', params: { type: 'rejected' } }, 'dose'],
        ['a share above one', { name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 2 } }, 'dose'],
    ])('refuses %s and names the field', async (_name, fault, field) => {
        const { status, json } = await call('POST', '/_faults', fault)

        expect(status).toBe(400)
        expect(json.problems).toEqual(expect.arrayContaining([expect.stringMatching(new RegExp(`^${field}`))]))
        expect(await send(ALICE)).toBe('sent')
    })
})
