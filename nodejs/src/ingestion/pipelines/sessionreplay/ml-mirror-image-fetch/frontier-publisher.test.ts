import { KafkaProducerWrapper } from '~/common/kafka/producer'
import { parseJSON } from '~/common/utils/json-parse'

import { FetchCandidate, MAX_HOPS } from './collected-urls-record'
import { FrontierPublisher } from './frontier-publisher'

const FRONTIER = 'session_replay_image_fetch'
const TIERS = [
    { topic: 'retry_1m', delayMs: 60_000 },
    { topic: 'retry_10m', delayMs: 600_000 },
    { topic: 'retry_1h', delayMs: 3_600_000 },
]

function candidate(overrides: Partial<FetchCandidate> = {}): FetchCandidate {
    return {
        ref: 'imageurl:team:originalhash0000000000',
        urlHash: 'originalhash0000000000',
        url: 'https://cdn.example.com/a.png',
        host: 'cdn.example.com',
        domain: 'example.com',
        pseudoTeam: 'team',
        capturedAtMs: 1_700_000_000_000,
        hopsRemaining: MAX_HOPS,
        notBeforeMs: 0,
        ...overrides,
    }
}

function build(): { publisher: FrontierPublisher; sent: { topic: string; key: string; body: any }[] } {
    const sent: { topic: string; key: string; body: any }[] = []
    const producer = {
        produce: ({ topic, key, value }: { topic: string; key: Buffer; value: Buffer }) => {
            sent.push({ topic, key: key.toString(), body: parseJSON(value.toString()) })
            return Promise.resolve()
        },
    } as unknown as KafkaProducerWrapper
    return { publisher: new FrontierPublisher(producer, { frontierTopic: FRONTIER, delayTiers: TIERS }), sent }
}

describe('FrontierPublisher', () => {
    it('keeps the original ref when handing a redirect target on (requirement 10)', async () => {
        // The recording points at the original ref. A hash of the redirect target names an image
        // nothing refers to, so the fetch would succeed and the image would still be unreachable.
        const { publisher, sent } = build()

        await publisher.republish(
            candidate(),
            { url: 'https://img.other.net/a.png', host: 'img.other.net', domain: 'other.net' },
            'redirect'
        )

        expect(sent).toHaveLength(1)
        expect(sent[0].key).toBe('other.net')
        expect(sent[0].body.urls[0]).toEqual({
            ref: 'imageurl:team:originalhash0000000000',
            url: 'https://img.other.net/a.png',
            host: 'img.other.net',
        })
    })

    it('spends a hop on every republish (requirement 11)', async () => {
        const { publisher, sent } = build()

        await publisher.republish(candidate({ hopsRemaining: 4 }), targetOf(), 'retry', 0)

        expect(sent[0].body.hopsRemaining).toBe(3)
    })

    it('refuses to republish a URL with one hop left, so nothing circulates forever', async () => {
        const { publisher, sent } = build()

        const published = await publisher.republish(candidate({ hopsRemaining: 1 }), targetOf(), 'retry', 0)

        expect(published).toBe(false)
        expect(sent).toEqual([])
    })

    it.each([
        ['a retry with no period named', 0, 'retry_1m'],
        ['a wait inside the first tier', 30_000, 'retry_1m'],
        ['a wait between tiers', 120_000, 'retry_10m'],
        ['a wait past every tier', 24 * 3_600_000, 'retry_1h'],
    ])('parks %s in the right topic', async (_name, waitMs, topic) => {
        const { publisher, sent } = build()

        await publisher.republish(candidate(), targetOf(), 'retry', waitMs)

        expect(sent[0].topic).toBe(topic)
    })

    it('never sends a retry straight back to the frontier (requirement 14)', async () => {
        // A retry sent to the frontier is a loop: the consumer reads the record, meets the same
        // condition, and publishes it again, spending a hop each lap until the URL is written off
        // without ever being fetched.
        const { publisher, sent } = build()

        await publisher.republish(candidate(), targetOf(), 'retry', 0)

        expect(sent[0].topic).not.toBe(FRONTIER)
        expect(sent[0].body.notBeforeMs).toBeGreaterThan(Date.now())
    })

    it('sends a redirect to the frontier at once, because its target is ready', async () => {
        const { publisher, sent } = build()

        await publisher.republish(candidate(), targetOf(), 'redirect')

        expect(sent[0].topic).toBe(FRONTIER)
        expect(sent[0].body.notBeforeMs).toBe(0)
    })

    it('keeps the requested wait when it is longer than every tier (requirement 15)', async () => {
        // A site that names a day comes back after an hour. The record says it is not due, so the
        // consumer leaves it alone rather than fetching it 23 hours early.
        const { publisher, sent } = build()
        const before = Date.now()

        await publisher.republish(candidate(), targetOf(), 'retry', 24 * 3_600_000)

        expect(sent[0].body.notBeforeMs).toBeGreaterThanOrEqual(before + 24 * 3_600_000)
    })

    it('holds a short wait for the whole period of the tier it parks in', async () => {
        const { publisher, sent } = build()
        const before = Date.now()

        await publisher.republish(candidate(), targetOf(), 'retry', 30_000)

        expect(sent[0].body.notBeforeMs).toBeGreaterThanOrEqual(before + 60_000)
    })

    it('reports a failed publish rather than throwing', async () => {
        const producer = { produce: () => Promise.reject(new Error('broker down')) } as unknown as KafkaProducerWrapper
        const publisher = new FrontierPublisher(producer, { frontierTopic: FRONTIER, delayTiers: TIERS })

        // One failed produce must not abandon the rest of the batch.
        await expect(publisher.republish(candidate(), targetOf(), 'retry', 0)).resolves.toBe(false)
    })
})

function targetOf(): { url: string; host: string; domain: string } {
    return { url: 'https://cdn.example.com/a.png', host: 'cdn.example.com', domain: 'example.com' }
}
