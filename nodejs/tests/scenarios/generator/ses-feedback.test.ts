import http from 'http'
import { AddressInfo } from 'net'

import type { TruthRecord } from '../provider-edge'
import { watchSesFeedback } from './ses-feedback'

const UNIT = 'run-a-1'
const NEVER_ABORTED = new AbortController().signal

type Feedback = Pick<TruthRecord, 'unitId' | 'status' | 'detail'> & Partial<Pick<TruthRecord, 'kind'>>

function startEdge(feedback: Feedback[]): Promise<{ url: string; close(): Promise<void> }> {
    const records: TruthRecord[] = feedback.map((record, i) => ({
        seq: i + 1,
        at: new Date(0).toISOString(),
        kind: 'ses.feedback',
        fault: 'ses.reject',
        ...record,
    }))
    const server = http.createServer((req, res) => {
        const after = Number(new URL(req.url!, 'http://edge').searchParams.get('after'))
        const page = records.slice(after)
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
})
