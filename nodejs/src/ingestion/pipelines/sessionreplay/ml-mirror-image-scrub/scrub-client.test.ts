import { Server, createServer } from 'node:http'
import { AddressInfo } from 'node:net'

import { ScrubAborted, ScrubClient, ScrubContractError } from './scrub-client'

type Reply = { status: number; body?: string }

describe('ScrubClient', () => {
    let server: Server
    let replies: Reply[]
    let requests: number

    // A real loopback server rather than a mocked `request`: the retry loop only matters in terms of
    // what it does with actual responses, and the 503 shed path in particular is a status the sidecar
    // sends without reading the body, which a mock would not reproduce.
    beforeEach(async () => {
        replies = []
        requests = 0
        server = createServer((req, res) => {
            requests += 1
            req.resume()
            const reply = replies.shift() ?? { status: 200, body: 'scrubbed' }
            req.on('end', () => res.writeHead(reply.status).end(reply.body ?? ''))
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    })

    afterEach(async () => {
        await new Promise((resolve) => server.close(resolve))
    })

    const client = (): ScrubClient =>
        new ScrubClient(
            `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
            1000,
            // Backoff is asserted separately; sleeping for real would only make this slow and flaky.
            () => Promise.resolve(),
            () => 1
        )

    it.each([
        ['shed with 503', 503],
        ['a 500 from a struggling sidecar', 500],
        ['a 502 from a half-started sidecar', 502],
        ['a 429', 429],
    ])('keeps waiting through %s until the sidecar returns bytes', async (_label, status) => {
        // The regression this exists for: a bounded retry that gives up turns a saturated sidecar
        // into permanent data loss, when Kafka is already holding the image durably and the only
        // cost of waiting is lag. Nothing here may resolve to null or throw.
        replies = Array.from({ length: 25 }, () => ({ status, body: '' }))

        await expect(client().scrub(Buffer.from('image'))).resolves.toEqual(Buffer.from('scrubbed'))
        expect(requests).toBe(26)
    })

    it.each([
        ['a misdirected URL or renamed route', 404, ''],
        ['a drifted request contract', 400, ''],
        ['success with no bytes', 200, ''],
    ])('fails the batch on %s rather than waiting on it', async (_label, status, body) => {
        // Waiting only makes sense for answers a later attempt could change. These say the deployment
        // is wrong, and waiting on them forever would turn a config mistake into a pod that consumes
        // nothing, passes every probe, and shows up only as lag hours later.
        replies = [{ status, body }]

        await expect(client().scrub(Buffer.from('image'))).rejects.toThrow(ScrubContractError)
        expect(requests).toBe(1)
    })

    it.each([
        ['undecodable', 422],
        ['too large', 413],
    ])('gives up immediately on %s, which no retry could change', async (_label, status) => {
        replies = [{ status }]

        await expect(client().scrub(Buffer.from('image'))).resolves.toBeNull()
        expect(requests).toBe(1)
    })

    it('stops waiting when the caller hangs up', async () => {
        // The one escape from the loop. Without it a shutdown would block on a sidecar that is never
        // going to answer, and the pod would have to be killed rather than draining.
        replies = Array.from({ length: 50 }, () => ({ status: 503, body: '' }))
        const controller = new AbortController()
        const scrubbing = client().scrub(Buffer.from('image'), controller.signal)
        controller.abort()

        await expect(scrubbing).rejects.toThrow(ScrubAborted)
    })
})
