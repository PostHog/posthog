import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { CyclotronJobInvocationGlobals } from '~/types'

import { SAMPLE_GLOBALS_CONTEXTS } from './sampleGlobalsContexts'

jest.mock('posthog-js')

type MockResponse = [number, Record<string, any>]

const RECENT_ISSUE_ID = '01936e7f-d7ff-7314-b2d4-7627981e34f0'
const RECENT_FINGERPRINT = 'recent-fingerprint-7f3a'
const OLD_ISSUE_ID = '01936e7f-0000-7000-8000-000000000001'
const OLD_FINGERPRINT = 'old-fingerprint-2c9e'
const MERGED_INTO_ISSUE_ID = '01936e7f-1111-7000-8000-000000000002'
const EXCEPTION_TIMESTAMP = '2026-11-01T12:00:00Z'
const EXCEPTION_PROPERTIES = {
    deploy_tier: 'canary',
    name: 'exception-name-should-lose',
    $exception_list: [{ type: 'TypeError', value: 'x is undefined' }],
}

const FOUND_RECENT_ISSUE: MockResponse = [200, { results: [[RECENT_ISSUE_ID, RECENT_FINGERPRINT]] }]
const NO_RECENT_ISSUE: MockResponse = [200, { results: [] }]
const FOUND_EXCEPTION = 'found'
const LOOKUP_FAILED = 'failed'
const QUERY_FAILED: MockResponse = [500, { detail: 'boom' }]

const exampleGlobals = { event: { properties: {} } } as unknown as CyclotronJobInvocationGlobals

function useErrorTrackingApiMocks({
    recentIssues,
    monthIssues = QUERY_FAILED,
    exceptionByFingerprint,
}: {
    recentIssues: MockResponse
    monthIssues?: MockResponse
    exceptionByFingerprint: Record<string, typeof FOUND_EXCEPTION | typeof LOOKUP_FAILED>
}): void {
    useMocks({
        get: {
            '/api/projects/:team_id/error_tracking/fingerprints/': {
                results: [
                    {
                        id: 'fp-record',
                        fingerprint: OLD_FINGERPRINT,
                        issue_id: OLD_ISSUE_ID,
                        created_at: EXCEPTION_TIMESTAMP,
                    },
                ],
            },
            '/api/projects/:team_id/error_tracking/issues/:id/': ({ params }) => ({
                id: params.id,
                name: 'TypeError',
                status: 'active',
                severity: 'high',
                assignee: null,
            }),
        },
        post: {
            '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                const { query } = (await request.json()) as { query: Record<string, any> }
                if (query.kind === 'HogQLQuery') {
                    return query.query.includes('INTERVAL 30 DAY') ? monthIssues : recentIssues
                }
                const filter = JSON.stringify(query.properties ?? query.where)
                const fingerprint = Object.keys(exceptionByFingerprint).find((key) => filter.includes(key))
                if (!fingerprint) {
                    return [200, { results: [] }]
                }
                if (exceptionByFingerprint[fingerprint] === LOOKUP_FAILED) {
                    return QUERY_FAILED
                }
                const uuid = `uuid-${fingerprint}`
                return query.select.includes('*')
                    ? [200, { results: [[{ uuid, properties: EXCEPTION_PROPERTIES, timestamp: EXCEPTION_TIMESTAMP }]] }]
                    : [200, { results: [[uuid, EXCEPTION_TIMESTAMP]] }]
            },
        },
    })
}

function issueFields(fingerprint: string): Record<string, any> {
    return { name: 'TypeError', description: 'PostHog test alert', status: 'active', severity: 'high', fingerprint }
}

describe('SAMPLE_GLOBALS_CONTEXTS error-tracking', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    it.each([
        [
            'a recently active issue with its latest exception properties, issue fields winning on a collision',
            { recentIssues: FOUND_RECENT_ISSUE, exceptionByFingerprint: { [RECENT_FINGERPRINT]: FOUND_EXCEPTION } },
            RECENT_ISSUE_ID,
            {
                ...EXCEPTION_PROPERTIES,
                ...issueFields(RECENT_FINGERPRINT),
                exception_timestamp: EXCEPTION_TIMESTAMP,
            },
        ],
        [
            'an issue active in the last 30 days when none was active in the last day',
            {
                recentIssues: NO_RECENT_ISSUE,
                monthIssues: FOUND_RECENT_ISSUE,
                exceptionByFingerprint: { [RECENT_FINGERPRINT]: FOUND_EXCEPTION },
            },
            RECENT_ISSUE_ID,
            { ...EXCEPTION_PROPERTIES, ...issueFields(RECENT_FINGERPRINT), exception_timestamp: EXCEPTION_TIMESTAMP },
        ],
        [
            'a fingerprint record, without a wider retry, when the recently active issues query fails',
            {
                recentIssues: QUERY_FAILED,
                monthIssues: FOUND_RECENT_ISSUE,
                exceptionByFingerprint: { [OLD_FINGERPRINT]: FOUND_EXCEPTION },
            },
            OLD_ISSUE_ID,
            { ...EXCEPTION_PROPERTIES, ...issueFields(OLD_FINGERPRINT), exception_timestamp: EXCEPTION_TIMESTAMP },
        ],
        [
            'issue fields only when the exception lookup fails',
            { recentIssues: FOUND_RECENT_ISSUE, exceptionByFingerprint: { [RECENT_FINGERPRINT]: LOOKUP_FAILED } },
            RECENT_ISSUE_ID,
            issueFields(RECENT_FINGERPRINT),
        ],
    ] as const)('samples %s', async (_, mocks, expectedIssueId, expectedProperties) => {
        useErrorTrackingApiMocks(mocks)

        const sample = await SAMPLE_GLOBALS_CONTEXTS['error-tracking']!(exampleGlobals)

        expect(sample.event.distinct_id).toBe(expectedIssueId)
        expect(sample.event.properties).toEqual(expectedProperties)
    })

    it('samples the issue a fingerprint belongs to now, when its exceptions name an issue merged since', async () => {
        useErrorTrackingApiMocks({
            recentIssues: FOUND_RECENT_ISSUE,
            exceptionByFingerprint: { [RECENT_FINGERPRINT]: FOUND_EXCEPTION },
        })
        const realFetch = globalThis.fetch
        // MSW follows a 308 that has no Location header, but a browser returns it, so answer this request before MSW
        jest.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
            const url = new URL(String(input instanceof Request ? input.url : input), location.origin)
            return url.pathname.endsWith(`/issues/${RECENT_ISSUE_ID}/`) &&
                url.searchParams.get('fingerprint') === RECENT_FINGERPRINT
                ? Promise.resolve(
                      new Response(JSON.stringify({ issue_id: MERGED_INTO_ISSUE_ID }), {
                          status: 308,
                          headers: { 'Content-Type': 'application/json' },
                      })
                  )
                : realFetch(input, init)
        })

        const sample = await SAMPLE_GLOBALS_CONTEXTS['error-tracking']!(exampleGlobals)

        expect(sample.event.distinct_id).toBe(MERGED_INTO_ISSUE_ID)
        expect(sample.event.properties).toEqual({
            ...EXCEPTION_PROPERTIES,
            ...issueFields(RECENT_FINGERPRINT),
            exception_timestamp: EXCEPTION_TIMESTAMP,
        })
    })
})
