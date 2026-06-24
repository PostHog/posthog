import { Team } from '../../types'
import { extractRequestApiKey, isPostHogIngestUrl, isSelfReferentialIngestFetch } from './self-loop-guard'

// Synthetic, non-production values. OWN_TOKEN is the project the destination runs in;
// OTHER_TOKEN is a different project (legitimate cross-project replication).
const OWN_TOKEN = 'phc_synthetic_own_0000000000000000'
const OWN_SECRET_TOKEN = 'phsx_synthetic_own_secret_00000000'
const OTHER_TOKEN = 'phc_synthetic_other_111111111111111'

const TEAM: Pick<Team, 'api_token' | 'secret_api_token'> = {
    api_token: OWN_TOKEN,
    secret_api_token: OWN_SECRET_TOKEN,
}

const INGEST_URL = 'https://us.i.posthog.com/capture/'
const BATCH_URL = 'https://eu.i.posthog.com/batch/'
const LOGS_URL = 'https://us.i.posthog.com/i/v1/logs'
const API_URL = 'https://us.posthog.com/api/projects/100/insights/'
const EXTERNAL_URL = 'https://external.example.com/webhook'

const captureBody = (event: string, properties: Record<string, unknown> = {}, apiKey = OWN_TOKEN): string =>
    JSON.stringify({ api_key: apiKey, event, distinct_id: 'synthetic_user_1', properties })

// The shape a replicator posts to /batch/ - the primary real self-loop case.
const batchBody = (events: string[], apiKey = OWN_TOKEN): string =>
    JSON.stringify({
        api_key: apiKey,
        historical_migration: false,
        batch: events.map((event) => ({ event, distinct_id: 'synthetic_user_1', properties: {} })),
    })

const detect = (overrides: { url?: string; body?: string | null }): boolean =>
    isSelfReferentialIngestFetch({
        url: overrides.url ?? INGEST_URL,
        body: overrides.body === undefined ? captureBody('replicated_event') : overrides.body,
        team: TEAM,
    })

describe('self-loop-guard', () => {
    describe('isPostHogIngestUrl', () => {
        it.each([
            ['https://us.i.posthog.com/capture/', true],
            ['https://us.i.posthog.com/capture', true],
            ['https://eu.i.posthog.com/batch/', true],
            ['https://us.i.posthog.com/e/', true],
            ['https://us.i.posthog.com/track/', true],
            ['https://us.i.posthog.com/i/v0/e/', true],
            ['https://us.i.posthog.com/capture/?api_key=abc', true],
            ['https://posthog.com/capture', true],
            // observability + REST endpoints are NOT ingestion - cannot form a loop
            ['https://us.i.posthog.com/i/v1/logs', false],
            ['https://us.posthog.com/api/projects/100/insights/', false],
            ['https://us.i.posthog.com/decide', false],
            // non-posthog hosts
            ['https://external.example.com/capture', false],
            ['https://posthog.com.evil.com/capture', false],
            ['https://notposthog.com/capture', false],
            ['not a url', false],
        ])('classifies %s as ingest=%s', (url, expected) => {
            expect(isPostHogIngestUrl(url)).toBe(expected)
        })
    })

    describe('extractRequestApiKey', () => {
        it('reads the top-level api_key field', () => {
            expect(extractRequestApiKey(captureBody('e'), INGEST_URL)).toBe(OWN_TOKEN)
        })

        it.each(['token', 'api_token'])('reads the top-level %s field', (field) => {
            expect(extractRequestApiKey(JSON.stringify({ [field]: OWN_TOKEN }), INGEST_URL)).toBe(OWN_TOKEN)
        })

        it('reads the api_key query parameter when body has none', () => {
            expect(extractRequestApiKey('', `${INGEST_URL}?api_key=${OWN_TOKEN}`)).toBe(OWN_TOKEN)
        })

        it('reads the top-level api_key from a batch body (the replicator shape)', () => {
            expect(extractRequestApiKey(batchBody(['e1', 'e2']), INGEST_URL)).toBe(OWN_TOKEN)
        })

        it('does NOT treat $lib_token in event properties as the request credential', () => {
            // The SDK auto-attaches the team token as $lib_token on event properties. That
            // is metadata, not an intent to ingest as the project - it must not be matched.
            const body = JSON.stringify({ event: 'ticket_updated', properties: { $lib_token: OWN_TOKEN } })
            expect(extractRequestApiKey(body, API_URL)).toBeNull()
        })

        it('returns null for an unparseable body and no query token', () => {
            expect(extractRequestApiKey('not-json{{', INGEST_URL)).toBeNull()
        })
    })

    describe('isSelfReferentialIngestFetch', () => {
        // The `false` rows double as the incident regression matrix: cross-project tokens,
        // $lib_token SDK metadata, REST/observability endpoints, and substring matches must
        // never be flagged.
        it.each([
            { case: 'capture to ingest endpoint with the project own token', args: {}, expected: true },
            {
                case: 'batch replicator posting to /batch/ with the project own token',
                args: { url: BATCH_URL, body: batchBody(['e1', 'e2']) },
                expected: true,
            },
            {
                case: 'project own token on the URL query string',
                args: { url: `${INGEST_URL}?api_key=${OWN_TOKEN}`, body: '' },
                expected: true,
            },
            {
                case: 'project secret token on the URL query string',
                args: { url: `${INGEST_URL}?api_key=${OWN_SECRET_TOKEN}`, body: '' },
                expected: true,
            },
            {
                case: 'capture authenticated with the project secret token',
                args: { body: captureBody('e', {}, OWN_SECRET_TOKEN) },
                expected: true,
            },
            {
                case: 'batch posting to /batch/ with a different project token',
                args: { url: BATCH_URL, body: batchBody(['e1', 'e2'], OTHER_TOKEN) },
                expected: false,
            },
            { case: 'external (non-PostHog) fetch', args: { url: EXTERNAL_URL }, expected: false },
            { case: 'observability logs endpoint (not ingestion)', args: { url: LOGS_URL }, expected: false },
            {
                case: 'workflow step posting to a PostHog REST API endpoint (with $lib_token in body)',
                args: { url: API_URL, body: JSON.stringify({ status: 'open', properties: { $lib_token: OWN_TOKEN } }) },
                expected: false,
            },
            {
                case: 'cross-project replication (different project token)',
                args: { body: captureBody('any_event', {}, OTHER_TOKEN) },
                expected: false,
            },
            {
                case: 'team token only as $lib_token, not the api_key',
                args: { body: JSON.stringify({ event: 'alpha', properties: { $lib_token: OWN_TOKEN } }) },
                expected: false,
            },
            {
                case: 'team token a substring of an unrelated field',
                args: { body: JSON.stringify({ event: 'alpha', properties: { ref: `${OWN_TOKEN}_extra` } }) },
                expected: false,
            },
            {
                case: 'ingest fetch carrying no credential at all',
                args: { body: JSON.stringify({ event: 'alpha' }) },
                expected: false,
            },
        ])('returns $expected for: $case', ({ args, expected }) => {
            expect(detect(args)).toBe(expected)
        })
    })
})
