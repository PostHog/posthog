import { CardFault, ProviderEdge, TruthHead, TruthPage, startProviderEdge } from '.'
import { Destination, SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import { createHash } from 'crypto'
import http from 'http'

import { EmailTrackingCodeSigner } from '~/cdp/services/messaging/helpers/tracking-code'
import { parseJSON } from '~/common/utils/json-parse'
import { internalFetch } from '~/common/utils/request'

import { ruleOf } from './faults'

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

    const send = (to: string | Destination, trackingCode?: string): Promise<string> =>
        ses
            .send(
                new SendEmailCommand({
                    FromEmailAddress: 'flows@www.example.com',
                    Destination: typeof to === 'string' ? { ToAddresses: [to] } : to,
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

    const call = async <T = unknown>(
        method: string,
        path: string,
        body?: object | null
    ): Promise<{ status: number; json: T }> => {
        const response = await internalFetch(`${edge.url}${path}`, {
            method,
            headers: { 'content-type': 'application/json' },
            body: body === undefined ? undefined : JSON.stringify(body),
        })
        const text = await response.text()
        return { status: response.status, json: (text ? parseJSON(text) : undefined) as T }
    }

    const truth = async (query = ''): Promise<TruthPage> => (await call<TruthPage>('GET', `/_truth${query}`)).json

    const addFault = async (fault: object): Promise<string> => {
        const { status, json } = await call<{ id: string }>('POST', '/_faults', fault)
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
        expect(await send(ALICE)).toBe('sent')

        expect((await truth()).records[0].detail.message!.tracked).toBeUndefined()
    })

    it('serves each sent attachment over the truth endpoint as its size and digest instead of its bytes', async () => {
        const invoice = Buffer.from('%PDF-1.4 invented invoice')
        const logo = Buffer.from('invented logo pixels')

        await ses.send(
            new SendEmailCommand({
                FromEmailAddress: 'flows@www.example.com',
                Destination: { ToAddresses: [ALICE] },
                Content: {
                    Simple: {
                        Subject: { Data: 'Hello' },
                        Body: { Html: { Data: '<img src="cid:logo">' } },
                        Attachments: [
                            { FileName: 'invoice.pdf', ContentType: 'application/pdf', RawContent: invoice },
                            {
                                FileName: 'logo.png',
                                ContentType: 'image/png',
                                ContentId: 'logo',
                                ContentDisposition: 'INLINE',
                                RawContent: logo,
                            },
                        ],
                    },
                },
            })
        )

        const sha256 = (bytes: Buffer): string => createHash('sha256').update(bytes).digest('hex')
        expect((await truth()).records[0].detail.message!.attachments).toEqual([
            {
                filename: 'invoice.pdf',
                contentType: 'application/pdf',
                inline: false,
                size: invoice.length,
                sha256: sha256(invoice),
            },
            {
                filename: 'logo.png',
                contentType: 'image/png',
                contentId: 'logo',
                inline: true,
                size: logo.length,
                sha256: sha256(logo),
            },
        ])
    })

    it('answers a request target that is not a URL with a 400', async () => {
        expect(await call('GET', '//edge:99999/')).toEqual({
            status: 400,
            json: { message: 'The request target is not a URL.' },
        })
    })

    const subject = { Simple: { Subject: { Data: 'Hello' } } }

    it.each<[string, object | null, string]>([
        [
            'an address list that is not a list',
            { FromEmailAddress: 'flows@www.example.com', Destination: { ToAddresses: ALICE }, Content: subject },
            'Destination.ToAddresses',
        ],
        [
            'a null body part',
            {
                FromEmailAddress: 'flows@www.example.com',
                Destination: { ToAddresses: [ALICE] },
                Content: { Simple: { Subject: { Data: 'Hello' }, Body: { Text: null } } },
            },
            'Content.Simple.Body.Text',
        ],
        ['no sender', { Destination: { ToAddresses: [ALICE] }, Content: subject }, 'FromEmailAddress'],
        ['a body that is not an object', null, 'request'],
    ])('records a send with %s as a 400 naming the field', async (_name, body, field) => {
        const { status } = await call('POST', '/v2/email/outbound-emails', body)

        expect(status).toBe(400)
        expect((await truth()).records).toEqual([
            expect.objectContaining({ status: 400, detail: { error: expect.stringContaining(`${field}: `) } }),
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

    it('answers sends over the throttle rate with the throttling error the email worker reschedules', async () => {
        const start = Date.now()
        const clock = jest.spyOn(Date, 'now').mockReturnValue(start)
        try {
            await addFault({ name: 'ses.throttle', params: { rate: 2 } })
            expect(await sendEach([ALICE, BOB, ALICE])).toEqual(['sent', 'sent', 'TooManyRequestsException'])

            clock.mockReturnValue(start + 1000)

            expect(await sendEach([ALICE, BOB, ALICE])).toEqual(['sent', 'sent', 'TooManyRequestsException'])
            expect((await truth()).records.map((record) => [record.unitId, record.status, record.fault])).toEqual([
                ['run-1-1', 200, undefined],
                ['run-1-2', 200, undefined],
                ['run-1-1', 429, 'ses.throttle'],
                ['run-1-1', 200, undefined],
                ['run-1-2', 200, undefined],
                ['run-1-1', 429, 'ses.throttle'],
            ])
        } finally {
            clock.mockRestore()
        }
    })

    it.each<[string, CardFault[], string[], string[]]>([
        [
            'counts only the sends that go out against the throttle rate',
            [
                { name: 'ses.throttle', params: { rate: 1 } },
                { name: 'ses.reject', params: { type: 'rejected' }, dose: { count: 1 } },
            ],
            [ALICE, ALICE, ALICE],
            ['MessageRejected', 'sent', 'TooManyRequestsException'],
        ],
        [
            'answers a send over the throttle rate with the throttle, though a rejection added before it matches',
            [
                { name: 'ses.reject', params: { type: 'rejected' }, match: { recipient: BOB }, dose: { share: 1 } },
                { name: 'ses.throttle', params: { rate: 1 } },
            ],
            [ALICE, BOB],
            ['sent', 'TooManyRequestsException'],
        ],
    ])('%s', async (_story, faults, recipients, outcomes) => {
        const clock = jest.spyOn(Date, 'now').mockReturnValue(Date.now())
        try {
            for (const fault of faults) {
                await addFault(fault)
            }

            expect(await sendEach(recipients)).toEqual(outcomes)
        } finally {
            clock.mockRestore()
        }
    })

    const rejectFor = (recipient: string): CardFault => ({
        name: 'ses.reject',
        params: { type: 'rejected' },
        match: { recipient },
        dose: { share: 1 },
    })

    it.each<[string, (forAlice: string) => string, string[]]>([
        ['one fault by its id', (forAlice) => `/_faults/${forAlice}`, ['sent', 'MessageRejected']],
        ['every fault', () => '/_faults', ['sent', 'sent']],
    ])('stops applying %s once the edge removes it', async (_name, pathOf, outcomes) => {
        const forAlice = await addFault(rejectFor(ALICE))
        await addFault(rejectFor(BOB))
        expect(await sendEach([ALICE, BOB])).toEqual(['MessageRejected', 'MessageRejected'])

        expect((await call('DELETE', pathOf(forAlice))).status).toBe(204)

        expect(await sendEach([ALICE, BOB])).toEqual(outcomes)
    })

    it.each<[string, Destination]>([
        ['cc', { ToAddresses: [ALICE], CcAddresses: [BOB] }],
        ['bcc', { ToAddresses: [ALICE], BccAddresses: [BOB] }],
    ])('applies a fault to a send whose %s addresses hold the matched recipient', async (_name, destination) => {
        await addFault(rejectFor(BOB))

        expect(await send(destination)).toBe('MessageRejected')
    })

    it('answers a fault id it no longer holds with a 404', async () => {
        const id = await addFault(rejectFor(ALICE))
        await call('DELETE', `/_faults/${id}`)

        expect((await call('DELETE', `/_faults/${id}`)).status).toBe(404)
    })

    it('keeps the truth when the faults are cleared', async () => {
        await addFault(rejectFor(ALICE))
        await sendEach([ALICE, BOB])
        await call('DELETE', '/_faults')
        await send(ALICE)

        expect((await truth()).records.map((record) => record.seq)).toEqual([1, 2, 3])
    })

    it.each<[string, { sendAt: number; releaseAt?: number }, boolean]>([
        ['observes a held fault from a send in the last moment of its window', { sendAt: 9_999 }, true],
        ['does not observe a held fault from a send after its window', { sendAt: 10_001 }, false],
        ['observes a held fault from a send just before the drive released it', { sendAt: 5, releaseAt: 6 }, true],
    ])('%s', async (_story, { sendAt, releaseAt }, observedFault) => {
        const start = Date.now()
        const clock = jest.spyOn(Date, 'now').mockReturnValue(start)
        const released = new AbortController()
        try {
            const held = edge.hold(ruleOf({ name: 'ses.reject', params: { type: 'rejected' }, dose: { count: 1 } }))
            const observed = held.observed(released.signal)
            clock.mockReturnValue(start + sendAt)
            const answer = await send(ALICE)
            if (releaseAt !== undefined) {
                clock.mockReturnValue(start + releaseAt)
                released.abort()
            }
            clock.mockReturnValue(start + 10_001)

            expect({ answer, observed: await observed }).toEqual({ answer: 'MessageRejected', observed: observedFault })
        } finally {
            clock.mockRestore()
        }
    })

    it.each<[string, string, TruthPage | TruthHead]>([
        [
            'after a sequence number up to the limit',
            '?after=1&limit=1',
            { records: [expect.objectContaining({ seq: 2, unitId: 'run-1-2' })], next: 2 },
        ],
        ['past its end as an empty page', '?after=3', { records: [], next: 3 }],
        [
            'with the default limit when the limit is zero',
            '?after=1&limit=0',
            { records: [expect.objectContaining({ seq: 2 }), expect.objectContaining({ seq: 3 })], next: 3 },
        ],
        ['as only its head', '/head', { head: 3 }],
    ])('pages the truth %s', async (_name, query, page) => {
        await sendEach([ALICE, BOB, ALICE])

        expect(await truth(query)).toEqual(page)
    })

    it.each([
        ['a fault no card can name', { name: 'ses.status', params: { status: 500 }, dose: { count: 1 } }, 'name'],
        ['a fault without a dose', { name: 'ses.reject', params: { type: 'rejected' } }, 'dose'],
        ['a share above one', { name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 2 } }, 'dose'],
        ['a throttle rate below one per second', { name: 'ses.throttle', params: { rate: 0.5 } }, 'params.rate'],
        [
            'a bounce on an edge that cannot sign feedback',
            { name: 'ses.reject', params: { type: 'bounce' }, dose: { count: 1 } },
            'params.type',
        ],
        [
            'a destination status that is not a final answer',
            { name: 'dest.status', params: { code: 100 }, dose: { count: 1 } },
            'params.code',
        ],
    ])('refuses %s and names the field', async (_name, fault, field) => {
        const { status, json } = await call<{ problems: string[] }>('POST', '/_faults', fault)

        expect(status).toBe(400)
        expect(json.problems).toEqual(expect.arrayContaining([expect.stringMatching(new RegExp(`^${field}`))]))
        expect(await send(ALICE)).toBe('sent')
    })
})
