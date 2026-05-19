/**
 * Shared helpers for the `/shared/{token}` unauthenticated playwright tests
 * (dashboard, insight, notebook). Centralises the network-leak assertion so a
 * silent 401/403 against /api/* fails the test even if the page still renders.
 *
 * The class of regression we keep tripping on is "shared mode silently leaks an
 * authenticated request" — the page may still render, but the leak is the
 * actual bug. Each unauth spec must assert on the network, not just the DOM.
 */
import { type BrowserContext, expect, type Page } from '@playwright/test'

interface RecordedFailure {
    method: string
    url: string
    status: number
}

interface RecordedRequest {
    method: string
    url: string
}

/**
 * Open a Page in the supplied context and record EVERY /api/* response with
 * status >= 400. The recording is unfiltered — what to allow vs flag is the
 * caller's job (see `expectNoTeamScopedApiLeaks` below).
 *
 * Also records every non-GET/HEAD /api/* request that was issued — these
 * should never fire in a /shared/{token} context because the sharing-access
 * token is read-only on the backend (`SharingAccessTokenAuthentication`).
 *
 * The expected use is to pass a fresh BrowserContext (created with empty
 * storage/cookies) to guarantee a logged-out browser, then assert against the
 * recorded failures after the page has settled.
 */
export async function openUnauthenticatedSharedPage(context: BrowserContext): Promise<{
    unauthPage: Page
    failedApiResponses: RecordedFailure[]
    nonGetApiRequests: RecordedRequest[]
}> {
    const unauthPage = await context.newPage()
    const failedApiResponses: RecordedFailure[] = []
    const nonGetApiRequests: RecordedRequest[] = []

    unauthPage.on('response', (response) => {
        const url = response.url()
        const status = response.status()
        if (!url.includes('/api/') || status < 400) {
            return
        }
        failedApiResponses.push({ method: response.request().method(), url, status })
    })

    unauthPage.on('request', (request) => {
        const url = request.url()
        const method = request.method()
        if (!url.includes('/api/') || method === 'GET' || method === 'HEAD') {
            return
        }
        nonGetApiRequests.push({ method, url })
    })

    return { unauthPage, failedApiResponses, nonGetApiRequests }
}

/**
 * Assert that no `/api/(environments|projects)/{team}/{resource}` request
 * 4xx'd while the shared page was rendering. Other paths (`/api/flags/`,
 * `/api/users/@me/`, `/api/organizations/...`, `/api/user_home_settings/`,
 * etc) are intentionally NOT covered here — they have legitimate unauth
 * failure modes, and the `client_request_failure` posthog event tags them
 * with `is_shared_view` so production telemetry still surfaces leaks.
 *
 * NOTE: this filter is deliberately narrow to avoid false positives. If a
 * regression leaks an org-scoped or user-scoped call, this assertion won't
 * catch it — broaden the filter (or add a sibling assertion) when those
 * paths become a concern.
 */
export function expectNoTeamScopedApiLeaks(failedApiResponses: ReadonlyArray<RecordedFailure>): void {
    const leaked = failedApiResponses.filter(({ url }) => /\/api\/(environments|projects)\/\d+\//.test(url))
    expect(leaked, `Unexpected team-scoped API failures in shared mode:\n${formatFailures(leaked)}`).toEqual([])
}

/**
 * Assert that no non-GET/HEAD request was issued to /api/* while the shared
 * page was rendering. The `handleFetch` short-circuit in `frontend/src/lib/api.ts`
 * is supposed to synthesize a 401 *before* hitting the network for any
 * mutation in shared/exporter views; if a request reaches Playwright's
 * `request` listener it means the guard regressed.
 */
export function expectNoNonGetApiRequests(nonGetApiRequests: ReadonlyArray<RecordedRequest>): void {
    expect(
        nonGetApiRequests,
        `Unexpected non-GET API requests in shared mode:\n${formatRequests(nonGetApiRequests)}`
    ).toEqual([])
}

function formatFailures(failures: ReadonlyArray<RecordedFailure>): string {
    return failures.map(({ method, status, url }) => `  ${method} ${url} -> ${status}`).join('\n')
}

function formatRequests(requests: ReadonlyArray<RecordedRequest>): string {
    return requests.map(({ method, url }) => `  ${method} ${url}`).join('\n')
}
