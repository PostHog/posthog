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
const EXCEPTION_TIMESTAMP = '2026-11-01T12:00:00Z'
const EXCEPTION_PROPERTIES = {
    deploy_tier: 'canary',
    name: 'exception-name-should-lose',
    $exception_list: [{ type: 'TypeError', value: 'x is undefined' }],
}

const FOUND_RECENT_ISSUE: MockResponse = [200, { results: [[RECENT_ISSUE_ID, RECENT_FINGERPRINT]] }]
const FOUND_EXCEPTION: MockResponse = [200, { results: [[JSON.stringify(EXCEPTION_PROPERTIES), EXCEPTION_TIMESTAMP]] }]
const QUERY_FAILED: MockResponse = [500, { detail: 'boom' }]

const exampleGlobals = { event: { properties: {} } } as unknown as CyclotronJobInvocationGlobals

// The fingerprints API only offers the old fingerprint, so a sample that names the recent one came
// from the recently active issues query.
function useErrorTrackingApiMocks({
    recentIssues,
    exceptionFor,
}: {
    recentIssues: MockResponse
    exceptionFor: Record<string, MockResponse>
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
                const body = (await request.json()) as { query: { query: string; tags?: { name?: string } } }
                const query = body.query.query
                if (body.query.tags?.name === 'hog_function_error_tracking_sample_issues') {
                    return recentIssues
                }
                // Answers only for a known fingerprint, so a lookup that loses its fingerprint filter gets nothing
                const fingerprint = Object.keys(exceptionFor).find((key) => query.includes(key))
                return fingerprint ? exceptionFor[fingerprint] : [200, { results: [] }]
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

    it.each([
        [
            'a recently active issue with its latest exception properties, issue fields winning on a collision',
            { recentIssues: FOUND_RECENT_ISSUE, exceptionFor: { [RECENT_FINGERPRINT]: FOUND_EXCEPTION } },
            RECENT_ISSUE_ID,
            {
                ...EXCEPTION_PROPERTIES,
                ...issueFields(RECENT_FINGERPRINT),
                exception_timestamp: EXCEPTION_TIMESTAMP,
            },
        ],
        [
            'a fingerprint record when the recently active issues query fails',
            { recentIssues: QUERY_FAILED, exceptionFor: { [OLD_FINGERPRINT]: FOUND_EXCEPTION } },
            OLD_ISSUE_ID,
            { ...EXCEPTION_PROPERTIES, ...issueFields(OLD_FINGERPRINT), exception_timestamp: EXCEPTION_TIMESTAMP },
        ],
        [
            'issue fields only when the exception lookup fails',
            { recentIssues: FOUND_RECENT_ISSUE, exceptionFor: { [RECENT_FINGERPRINT]: QUERY_FAILED } },
            RECENT_ISSUE_ID,
            issueFields(RECENT_FINGERPRINT),
        ],
    ] as const)('samples %s', async (_, mocks, expectedIssueId, expectedProperties) => {
        useErrorTrackingApiMocks(mocks)

        const sample = await SAMPLE_GLOBALS_CONTEXTS['error-tracking']!(exampleGlobals)

        expect(sample.event.distinct_id).toBe(expectedIssueId)
        expect(sample.event.properties).toEqual(expectedProperties)
    })
})
