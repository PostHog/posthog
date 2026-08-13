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
        ['no wait', 0, FRONTIER],
        ['a wait inside the first tier', 30_000, 'retry_1m'],
        ['a wait between tiers', 120_000, 'retry_10m'],
        ['a wait past every tier', 24 * 3_600_000, 'retry_1h'],
    ])('sends %s to the right topic', async (_name, waitMs, topic) => {
        // A wait longer than the longest tier comes back early, spends another hop, and waits
        // again. That is cheaper than a tier sized for the longest Retry-After a site can name.
        const { publisher, sent } = build()

        await publisher.republish(candidate(), targetOf(), 'retry', waitMs)

        expect(sent[0].topic).toBe(topic)
    })

    it('sets the earliest fetch time from the tier it chose (requirement 15)', async () => {
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
