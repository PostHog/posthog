import http from 'http'
import { AddressInfo } from 'net'
import { setTimeout as sleep } from 'timers/promises'

import type { TruthRecord } from '../provider-edge'
import { watchSesFeedback } from './ses-feedback'

const UNIT = 'run-a-1'
const NEVER_ABORTED = new AbortController().signal

type Feedback = Pick<TruthRecord, 'unitId' | 'status' | 'detail'> & Partial<Pick<TruthRecord, 'kind'>>

function truthRecord(seq: number, record: Feedback): TruthRecord {
    return { seq, at: new Date(0).toISOString(), kind: 'ses.feedback', fault: 'ses.reject', ...record }
}

function startEdge(feedback: Feedback[] | 'never drained'): Promise<{ url: string; close(): Promise<void> }> {
    const pageAfter = (after: number): TruthRecord[] =>
        feedback === 'never drained'
            ? [truthRecord(after + 1, { unitId: 'run-a-2', status: 200, detail: {} })]
            : feedback.map((record, i) => truthRecord(i + 1, record)).slice(after)
    const server = http.createServer((req, res) => {
        const after = Number(new URL(req.url!, 'http://edge').searchParams.get('after'))
        const page = pageAfter(after)
        res.writeHead(200, { 'content-type': 'application/json' }).end(
            JSON.stringify({ records: page, next: page.at(-1)?.seq ?? after })
        )
    })
    return new Promise((resolve) =>
        server.listen(0, '127.0.0.1', () =>
            resolve({
                url: `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
                close: () => new Promise((closed) => server.close(() => closed())),
            })
        )
    )
}

describe('watchSesFeedback', () => {
    it.each<[string, Feedback[], number[], string | undefined]>([
        [
            'settles once cdp-api answered 200 and the consumer caught up',
            [{ unitId: UNIT, status: 200, detail: {} }],
            [2, 0],
            undefined,
        ],
        [
            'names the error when the edge could not post the feedback',
            [{ unitId: UNIT, status: 0, detail: { error: 'The edge has no a feedback URL.' } }],
            [0],
            'the SES feedback was not taken: The edge has no a feedback URL.',
        ],
        [
            'names the status when cdp-api refused the feedback',
            [{ unitId: UNIT, status: 403, detail: {} }],
            [0],
            'the SES feedback was not taken: cdp-api answered 403',
        ],
        [
            'gives up when only another unit got feedback',
            [{ unitId: 'run-a-2', status: 200, detail: {} }],
            [0],
            'the edge recorded no SES feedback within 1s',
        ],
        [
            'gives up when the edge recorded only the send',
            [{ kind: 'ses.send', unitId: UNIT, status: 200, detail: {} }],
            [0],
            'the edge recorded no SES feedback within 1s',
        ],
        [
            'gives up when the consumer stays behind',
            [{ unitId: UNIT, status: 200, detail: {} }],
            [4],
            'the SES webhooks consumer was 4 messages behind after 1s',
        ],
    ])('%s', async (_story, feedback, lags, expected) => {
        const edge = await startEdge(feedback)
        const lag = (): Promise<number> => Promise.resolve(lags.length > 1 ? lags.shift()! : lags[0])
        try {
            const watch = watchSesFeedback({ edgeUrl: edge.url, lag, withinMs: 1000, pollMs: 5 })

            expect(await watch.settled(UNIT, NEVER_ABORTED)).toBe(expected)
        } finally {
            await edge.close()
        }
    })

    it('gives up at the deadline while the edge keeps recording other units', async () => {
        const edge = await startEdge('never drained')
        try {
            const watch = watchSesFeedback({ edgeUrl: edge.url, lag: () => Promise.resolve(0), withinMs: 50 })

            expect(await Promise.race([watch.settled(UNIT, NEVER_ABORTED), sleep(1000, 'still reading')])).toBe(
                'the edge recorded no SES feedback within 0.05s'
            )
        } finally {
            await edge.close()
        }
    })

    it('waits for a lag probe that started after the unit got its feedback', async () => {
        const feedback: Feedback[] = [{ unitId: 'run-a-1', status: 200, detail: {} }]
        const edge = await startEdge(feedback)
        const consumerBehindOnSecondBounce = (): Promise<number> => Promise.resolve(feedback.length > 1 ? 4 : 0)
        try {
            const watch = watchSesFeedback({
                edgeUrl: edge.url,
                lag: consumerBehindOnSecondBounce,
                withinMs: 200,
                pollMs: 1000,
            })
            await watch.settled('run-a-1', NEVER_ABORTED)
            feedback.push({ unitId: 'run-a-2', status: 200, detail: {} })

            expect(await watch.settled('run-a-2', NEVER_ABORTED)).toBe(
                'the SES webhooks consumer was 4 messages behind after 0.2s'
            )
        } finally {
            await edge.close()
        }
    })

    it.each<[string, Feedback[] | 'never drained']>([
        ['while it waits for feedback', []],
        ['while it waits for the consumer', [{ unitId: UNIT, status: 200, detail: {} }]],
        ['while the edge keeps recording other units', 'never drained'],
    ])('stops at an abort %s', async (_story, feedback) => {
        const edge = await startEdge(feedback)
        try {
            const watch = watchSesFeedback({ edgeUrl: edge.url, lag: () => Promise.resolve(4), pollMs: 5 })

            await expect(
                Promise.race([watch.settled(UNIT, AbortSignal.timeout(50)), sleep(1000, 'still waiting')])
            ).rejects.toMatchObject({ name: 'AbortError' })
        } finally {
            await edge.close()
        }
    })
})
