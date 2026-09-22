import {
    FetchCandidate,
    MAX_HOPS,
    MAX_JOBS_PER_RECORD,
    MAX_RECORD_BYTES,
    parseCollectedUrlsRecord,
    serializeFrontierRecord,
} from './collected-urls-record'

const REF = `imageurl:${'a'.repeat(22)}`

function candidate(overrides: Partial<FetchCandidate> = {}): FetchCandidate {
    return {
        originalRef: REF,
        currentUrl: 'https://cdn.example.com/a.png',
        host: 'cdn.example.com',
        origin: 'https://cdn.example.com',
        registrableDomain: 'example.com',
        remainingHops: MAX_HOPS,
        notBeforeMs: 0,
        firstSeenAtMs: 1_700_000_000_000,
        fetchCount: 0,
        republishCount: 0,
        lastRepublishReason: null,
        ...overrides,
    }
}

function record(overrides: Record<string, unknown> = {}): Buffer {
    return Buffer.from(
        JSON.stringify({
            v: 2,
            jobs: [
                {
                    originalRef: REF,
                    currentUrl: 'https://cdn.example.com/a.png',
                    remainingHops: MAX_HOPS,
                    notBeforeMs: 0,
                    firstSeenAtMs: 1_700_000_000_000,
                    fetchCount: 0,
                    republishCount: 0,
                    lastRepublishReason: null,
                    ...overrides,
                },
            ],
        })
    )
}

describe('frontier record', () => {
    it('round trips the durable job state', () => {
        const durableCandidate = candidate({ lastBlockReason: 'configuration_unreachable' })
        const parsed = parseCollectedUrlsRecord(serializeFrontierRecord([durableCandidate]), 'example.com')

        expect(parsed).toEqual({ ok: true, candidates: [durableCandidate], urlCount: 1, rejected: [], skipped: [] })
    })

    it('does not persist source partition attribution', () => {
        const parsed = parseCollectedUrlsRecord(
            serializeFrontierRecord([candidate({ sourcePartitions: [7] })]),
            'example.com'
        )

        expect(parsed).toEqual({ ok: true, candidates: [candidate()], urlCount: 1, rejected: [], skipped: [] })
    })

    it('accepts and removes the legacy low-origin-diversity marker', () => {
        expect(parseCollectedUrlsRecord(record({ lowOriginDiversityDeferred: true }), 'example.com')).toEqual({
            ok: true,
            candidates: [candidate()],
            urlCount: 1,
            rejected: [],
            skipped: [],
        })
    })

    it('drops a job with a non-boolean low-origin-diversity marker', () => {
        expect(parseCollectedUrlsRecord(record({ lowOriginDiversityDeferred: 'true' }), 'example.com')).toEqual({
            ok: false,
            reason: 'bad_url',
        })
    })

    it.each([
        ['missing value', null, 'example.com', 'malformed'],
        ['missing key', record(), null, 'malformed'],
        ['invalid JSON', Buffer.from('{'), 'example.com', 'malformed'],
        ['unknown version', Buffer.from('{"v":3,"jobs":[]}'), 'example.com', 'unsupported_version'],
        ['oversized bytes', Buffer.alloc(MAX_RECORD_BYTES + 1), 'example.com', 'oversized_record'],
        [
            'too many jobs',
            Buffer.from(JSON.stringify({ v: 2, jobs: Array(MAX_JOBS_PER_RECORD + 1).fill({}) })),
            'example.com',
            'oversized_record',
        ],
    ])('refuses %s', (_name, value, key, reason) => {
        expect(parseCollectedUrlsRecord(value, key)).toEqual({ ok: false, reason })
    })

    it.each([
        ['legacy team-scoped ref', `imageurl:${'b'.repeat(32)}:${'a'.repeat(22)}`, 'bad_ref'],
        ['byte ref', `image:${'b'.repeat(32)}:${'a'.repeat(22)}`, 'bad_ref'],
        ['credentials', 'https://user:pass@cdn.example.com/a.png', 'bad_url'],
        ['HTTP', 'http://cdn.example.com/a.png', 'bad_url'],
        ['non-default port', 'https://cdn.example.com:444/a.png', 'bad_url'],
        ['private address', 'https://127.0.0.1/a.png', 'bad_url'],
        ['non-canonical URL', 'https://CDN.EXAMPLE.COM/a.png', 'bad_url'],
    ])('drops a job with %s', (_name, value, reason) => {
        const overrides = value.startsWith('image') ? { originalRef: value } : { currentUrl: value }
        const parsed = parseCollectedUrlsRecord(record(overrides), 'example.com')

        expect(parsed).toEqual({ ok: false, reason })
    })

    it('skips a tracking beacon job and keeps the rest of the record', () => {
        const beacon = candidate({
            originalRef: `imageurl:${'b'.repeat(22)}`,
            currentUrl: 'https://analytics.twitter.com/i/adsct?txn_id=abc&p_id=Twitter',
            host: 'analytics.twitter.com',
            origin: 'https://analytics.twitter.com',
            registrableDomain: 'twitter.com',
        })
        const image = candidate({
            currentUrl: 'https://cdn.twitter.com/logo.png',
            host: 'cdn.twitter.com',
            origin: 'https://cdn.twitter.com',
            registrableDomain: 'twitter.com',
        })

        const parsed = parseCollectedUrlsRecord(serializeFrontierRecord([beacon, image]), 'twitter.com')

        expect(parsed).toEqual({
            ok: true,
            candidates: [image],
            urlCount: 2,
            rejected: [],
            skipped: [{ reason: 'tracking_beacon' }],
        })
    })

    it('skips a tracking beacon in a retained v1 record', () => {
        const pseudoTeam = 'b'.repeat(32)
        const value = Buffer.from(
            JSON.stringify({
                v: 1,
                pseudoTeam,
                capturedAtMs: 1_700_000_000_000,
                urls: [
                    {
                        ref: `imageurl:${pseudoTeam}:${'c'.repeat(22)}`,
                        url: 'https://t.co/i/adsct?txn_id=abc',
                        host: 't.co',
                    },
                ],
            })
        )

        expect(parseCollectedUrlsRecord(value, 't.co')).toEqual({
            ok: true,
            candidates: [],
            urlCount: 1,
            rejected: [],
            skipped: [{ reason: 'tracking_beacon' }],
        })
    })

    it('drops a job placed on another registrable-domain partition', () => {
        const parsed = parseCollectedUrlsRecord(record(), 'other.net')

        expect(parsed).toEqual({ ok: false, reason: 'foreign_domain' })
    })

    it('converts a retained v1 record into durable candidates', () => {
        const pseudoTeam = 'b'.repeat(32)
        const legacyRef = `imageurl:${pseudoTeam}:${'c'.repeat(22)}`
        const value = Buffer.from(
            JSON.stringify({
                v: 1,
                pseudoTeam,
                capturedAtMs: 1_700_000_000_000,
                hopsRemaining: 7,
                notBeforeMs: 1_700_000_060_000,
                urls: [
                    {
                        ref: legacyRef,
                        url: 'https://CDN.EXAMPLE.COM./a.png',
                        host: 'cdn.example.com.',
                    },
                ],
            })
        )

        expect(parseCollectedUrlsRecord(value, 'example.com.')).toEqual({
            ok: true,
            candidates: [
                candidate({
                    originalRef: legacyRef,
                    remainingHops: 7,
                    notBeforeMs: 1_700_000_060_000,
                }),
            ],
            urlCount: 1,
            rejected: [],
            skipped: [],
        })
    })

    it.each([
        ['remainingHops', MAX_HOPS + 1],
        ['notBeforeMs', -1],
        ['firstSeenAtMs', Number.POSITIVE_INFINITY],
        ['fetchCount', 1.5],
        ['republishCount', Number.MAX_SAFE_INTEGER + 1],
        ['lastRepublishReason', 'unknown'],
        ['lastBlockReason', 'unknown'],
    ])('drops an invalid %s', (field, value) => {
        const parsed = parseCollectedUrlsRecord(record({ [field]: value }), 'example.com')

        expect(parsed).toEqual({ ok: false, reason: 'bad_url' })
    })
})
