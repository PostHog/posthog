import { Server, createServer } from 'node:http'
import { AddressInfo } from 'node:net'

import { ScrubAborted, ScrubClient, ScrubContractError, ScrubPoisoned } from './scrub-client'

type Reply = { status: number; body?: string }

describe('ScrubClient', () => {
    let server: Server
    let replies: Reply[]
    let requests: number
    let replyFor: ((body: string) => Reply | undefined) | undefined

    // A real loopback server rather than a mocked `request`: the retry loop only matters in terms of
    // what it does with actual responses, and the 503 shed path in particular is a status the sidecar
    // sends without reading the body, which a mock would not reproduce.
    beforeEach(async () => {
        replies = []
        requests = 0
        replyFor = undefined
        server = createServer((req, res) => {
            requests += 1
            const chunks: Buffer[] = []
            req.on('data', (c: Buffer) => chunks.push(c))
            req.on('end', () => {
                // Keyed on the request body when a rule is set, so a poison image and its healthy
                // neighbours can be in flight at once, which is the only arrangement in which the
                // "failing while others succeed" rule means anything.
                const reply = replyFor?.(Buffer.concat(chunks).toString()) ??
                    replies.shift() ?? { status: 200, body: 'scrubbed' }
                res.writeHead(reply.status).end(reply.body ?? '')
            })
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
    })

    afterEach(async () => {
        await new Promise((resolve) => server.close(resolve))
    })

    const client = (deadLetters = false): ScrubClient =>
        new ScrubClient(
            `http://127.0.0.1:${(server.address() as AddressInfo).port}`,
            1000,
            deadLetters,
            // Backoff is asserted separately; sleeping for real would only make this slow and flaky.
            () => Promise.resolve(),
            () => 1
        )

    it.each([
        ['shed with 503', 503],
        ['a 500 from a struggling sidecar', 500],
        ['a 502 from a half-started sidecar', 502],
        ['a 429', 429],
        // Reachable from image content, not from a bad deployment: the sidecar's success path
        // returns whatever the scrub produced, so a zero-length result is a plain 200 with no body.
        ['success with no bytes', 200],
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
        ['a method the sidecar does not serve', 405, ''],
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

    it('never dead-letters on saturation alone, however long the sidecar sheds', async () => {
        // The safety property of the whole dead-letter path. Under a backlog every image waits a
        // long time, so anything keyed on waiting or failure count alone would park the entire
        // stream, which is the mass loss the wait exists to prevent arriving through another door.
        // Nothing succeeds here, so nothing may be blamed on any one image.
        replies = Array.from({ length: 400 }, () => ({ status: 503, body: '' }))

        await expect(client(true).scrub(Buffer.from('image'))).resolves.toEqual(Buffer.from('scrubbed'))
    })

    it('holds an image through a sidecar failing everything, rather than parking it for the outage', async () => {
        // A sidecar 500ing on every image is the sidecar, not the content, and parking images for it
        // would quarantine the whole stream for a bug that has nothing to do with them. How long it
        // rides out is bounded by Kafka's poll lease rather than chosen: the batch cannot return
        // while this image is in flight, so a pod that waits past the lease is fenced and the work
        // simply moves to another pod to be repeated.
        replies = Array.from({ length: 8 }, () => ({ status: 500, body: '' }))

        await expect(client(true).scrub(Buffer.from('image'))).resolves.toEqual(Buffer.from('scrubbed'))
    })

    it('parks an image eventually even with no peers to prove the sidecar works', async () => {
        // The success test cannot pass when nothing else is succeeding, and the images in a batch are
        // chosen by whoever produced them: fill one with content the sidecar rejects and no peer is
        // left to vouch for it. Without a way out, that stalls a partition shared by every team whose
        // records hash to it, which is worse than parking for an outage — parking keeps the bytes and
        // is loud, a stall keeps nothing moving and is silent.
        replies = Array.from({ length: 5000 }, () => ({ status: 500, body: '' }))

        await expect(client(true).scrub(Buffer.from('image'), undefined, 'ref-1')).rejects.toThrow(ScrubPoisoned)
    })

    /**
     * One image the sidecar always 500s on, alongside a stream it scrubs fine, in flight together.
     *
     * Returned wrapped, because awaiting an async function that returns a promise adopts that
     * promise instead of handing it back, which would await the poison scrub here rather than in the
     * assertion.
     */
    const poisonAmongHealthy = async (c: ScrubClient): Promise<{ inFlight: Promise<Buffer | null> }> => {
        replyFor = (body) => (body.startsWith('poison') ? { status: 500, body: '' } : undefined)
        const inFlight = c.scrub(Buffer.from('poison'), undefined, 'ref-1')
        inFlight.catch(() => {}) // settled by the caller; this only stops an unhandled rejection
        // Only a handful, deliberately: a poison image late in a batch has just its few concurrent
        // neighbours to prove the sidecar works, because the batch cannot finish while it is in
        // flight and the pod cannot poll for more. A gate needing more than that never opens.
        for (let i = 0; i < 4; i++) {
            await c.scrub(Buffer.from(`healthy-${i}`))
        }
        return { inFlight }
    }

    it('dead-letters an image that keeps failing while the sidecar succeeds on others', async () => {
        // The case the dead-letter topic exists for: the sidecar demonstrably works, and this one
        // image still cannot get through, so it is the content and it must stop holding the head of
        // its partition.
        const { inFlight } = await poisonAmongHealthy(client(true))

        await expect(inFlight).rejects.toThrow(ScrubPoisoned)
    })

    it('keeps waiting on a poison image when there is nowhere to park it', async () => {
        // Without a dead-letter destination the only alternative to waiting is discarding, so a
        // misconfigured producer must cost throughput on one partition rather than the image.
        const { inFlight } = await poisonAmongHealthy(client(false))
        replyFor = undefined

        await expect(inFlight).resolves.toEqual(Buffer.from('scrubbed'))
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
