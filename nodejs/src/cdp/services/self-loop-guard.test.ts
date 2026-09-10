import { parseJSON } from '~/common/utils/json-parse'

import { Team } from '../../types'
import {
    SELF_LOOP_DEPTH_PROPERTY,
    extractRequestApiKey,
    getSelfLoopDepth,
    injectSelfLoopDepth,
    isPostHogIngestUrl,
    isSelfReferentialIngestFetch,
} from './self-loop-guard'

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

    describe('getSelfLoopDepth / injectSelfLoopDepth (per-function)', () => {
        const FN = '019c6797-f409-0000-6b4c-d452176ca3c8'
        const OTHER_FN = '019d9077-abe4-0000-cd1e-be1d3ab0289f'

        it("stamps this function's depth onto a single-event body, preserving existing properties", () => {
            const props = parseJSON(
                injectSelfLoopDepth(captureBody('alpha', { foo: 'bar' }), FN, 3) as string
            ).properties
            expect(props.foo).toBe('bar')
            expect(props[SELF_LOOP_DEPTH_PROPERTY]).toEqual({ [FN]: 3 })
        })

        it("stamps this function's depth onto every entry of a batch body", () => {
            const parsed = parseJSON(injectSelfLoopDepth(batchBody(['a', 'b']), FN, 5) as string)
            expect(parsed.batch.map((e: any) => e.properties[SELF_LOOP_DEPTH_PROPERTY][FN])).toEqual([5, 5])
        })

        it("preserves other functions' depths in the map - only its own entry is touched", () => {
            const seeded = JSON.stringify({
                api_key: OWN_TOKEN,
                event: 'alpha',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: { [OTHER_FN]: 7 } },
            })
            expect(
                parseJSON(injectSelfLoopDepth(seeded, FN, 1) as string).properties[SELF_LOOP_DEPTH_PROPERTY]
            ).toEqual({
                [OTHER_FN]: 7,
                [FN]: 1,
            })
        })

        it('round-trips: reads back the depth it stamped for the same function', () => {
            const props = parseJSON(injectSelfLoopDepth(captureBody('alpha'), FN, 4) as string).properties
            expect(getSelfLoopDepth(props, FN)).toBe(4)
        })

        // A seeded array passes a naive object check but JSON.stringify drops the stamped key,
        // which would let the loop run uncapped. The array must be discarded for a real map.
        it('replaces a seeded array depth map with a real object that survives serialization', () => {
            const seeded = JSON.stringify({
                api_key: OWN_TOKEN,
                event: 'alpha',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: [1, 2, 3] },
            })
            const props = parseJSON(injectSelfLoopDepth(seeded, FN, 1) as string).properties
            expect(props[SELF_LOOP_DEPTH_PROPERTY]).toEqual({ [FN]: 1 })
            expect(getSelfLoopDepth(props, FN)).toBe(1)
        })

        // The cross-block regression: a destination is bounded ONLY by its own re-entries.
        // A huge depth for a *different* function must read as 0 for ours, so a deep chain of
        // unrelated functions can never trip the guard for a legitimately-running destination.
        it.each([
            { case: 'no depth map at all', properties: {}, expected: 0 },
            {
                case: 'a different function deep in the map (cross-block case)',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: { [OTHER_FN]: 50 } },
                expected: 0,
            },
            { case: 'malformed (non-object) map', properties: { [SELF_LOOP_DEPTH_PROPERTY]: 9 }, expected: 0 },
            { case: 'this function present', properties: { [SELF_LOOP_DEPTH_PROPERTY]: { [FN]: 6 } }, expected: 6 },
            // Untrusted input: a project owner can seed these on the event to try to delay the cap.
            {
                case: 'a seeded negative depth (bypass attempt) clamps to 0',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: { [FN]: -999 } },
                expected: 0,
            },
            {
                case: 'a non-finite depth is ignored',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: { [FN]: Infinity } },
                expected: 0,
            },
            {
                case: 'a fractional depth floors to an integer',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: { [FN]: 6.9 } },
                expected: 6,
            },
            {
                case: 'an array map (bypass attempt) reads as 0',
                properties: { [SELF_LOOP_DEPTH_PROPERTY]: [] },
                expected: 0,
            },
        ])('getSelfLoopDepth: $case -> $expected', ({ properties, expected }) => {
            expect(getSelfLoopDepth(properties as Record<string, unknown>, FN)).toBe(expected)
        })

        it.each([
            { case: 'unparseable', body: 'not-json{{' },
            { case: 'empty string', body: '' },
            { case: 'null', body: null },
        ])('returns a non-capture body unchanged: $case', ({ body }) => {
            expect(injectSelfLoopDepth(body, FN, 1)).toBe(body)
        })
    })
})
