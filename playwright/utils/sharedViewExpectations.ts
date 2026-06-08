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

/**
 * Open a Page in the supplied context and record EVERY /api/* response with
 * status >= 400. The recording is unfiltered — what to allow vs flag is the
 * caller's job (see `expectNoTeamScopedApiLeaks` below).
 *
 * The expected use is to pass a fresh BrowserContext (created with empty
 * storage/cookies) to guarantee a logged-out browser, then assert against the
 * recorded failures after the page has settled.
 */
export async function openUnauthenticatedSharedPage(context: BrowserContext): Promise<{
    unauthPage: Page
    failedApiResponses: RecordedFailure[]
}> {
    const unauthPage = await context.newPage()
    const failedApiResponses: RecordedFailure[] = []

    unauthPage.on('response', (response) => {
        const url = response.url()
        const status = response.status()
        if (!url.includes('/api/') || status < 400) {
            return
        }
        failedApiResponses.push({ method: response.request().method(), url, status })
    })

    return { unauthPage, failedApiResponses }
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

function formatFailures(failures: ReadonlyArray<RecordedFailure>): string {
    return failures.map(({ method, status, url }) => `  ${method} ${url} -> ${status}`).join('\n')
}
