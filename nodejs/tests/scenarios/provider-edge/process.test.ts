import { SESv2Client, SendEmailCommand } from '@aws-sdk/client-sesv2'
import net from 'net'

import { ruleOf } from './faults'
import { EdgeProcess, startEdgeProcess } from './process'

const ALICE = 'run-1-1@www.example.com'
const REJECT = ruleOf({ name: 'ses.reject', params: { type: 'rejected' }, dose: { share: 1 } })
const SOONER_THAN_THE_HOLD_WINDOW_MS = 5_000

describe('provider edge process', () => {
    let edge: EdgeProcess
    let ses: SESv2Client

    beforeEach(async () => {
        edge = await startEdgeProcess({ port: 0 })
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

    const send = (): Promise<string> =>
        ses
            .send(
                new SendEmailCommand({
                    FromEmailAddress: 'flows@www.example.com',
                    Destination: { ToAddresses: [ALICE] },
                    Content: { Simple: { Subject: { Data: 'Hello' }, Body: { Text: { Data: 'Hello there' } } } },
                })
            )
            .then(
                () => 'sent',
                (error: Error) => error.name
            )

    it('answers a send with a held fault, observes it, and lifts it on release', async () => {
        const held = await edge.hold(REJECT)
        const observed = held.observed()
        const answer = await send()
        const seen = await observed
        await held.release()

        expect({ answer, seen, after: await send() }).toEqual({ answer: 'MessageRejected', seen: true, after: 'sent' })
    })

    it.each([
        ['before the wait began', true],
        ['during the wait', false],
    ])(
        'stops waiting on a hold the drive ended %s',
        async (_when, endsFirst) => {
            const held = await edge.hold(REJECT)
            const holdEnds = new AbortController()
            if (endsFirst) {
                holdEnds.abort()
            }
            const observed = held.observed(holdEnds.signal)
            holdEnds.abort()

            expect(await observed).toBe(false)
        },
        SOONER_THAN_THE_HOLD_WINDOW_MS
    )

    it('lifts every held fault when the faults are cleared', async () => {
        await edge.hold(REJECT)
        await edge.clearFaults()

        expect(await send()).toBe('sent')
    })

    it('rejects startup on a port another listener holds', async () => {
        await expect(startEdgeProcess({ port: Number(new URL(edge.url).port) })).rejects.toThrow('EADDRINUSE')
    })

    it('frees its port by the time it has closed', async () => {
        const port = Number(new URL(edge.url).port)
        await edge.close()
        const listener = net.createServer()
        const bound = new Promise<string>((resolve) => {
            listener.once('error', (error: NodeJS.ErrnoException) => resolve(error.code ?? error.message))
            listener.listen(port, '127.0.0.1', () => resolve('bound'))
        })
        const outcome = await bound
        listener.close()
        edge = await startEdgeProcess({ port: 0 })

        expect(outcome).toBe('bound')
    })
})
