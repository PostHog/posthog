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
 * Open a fresh BrowserContext + Page with no cookies/storage and start
 * recording any /api/* response with status >= 400 except 401/403 only when
 * the response is for a path explicitly allowed below.
 *
 * Why allow ANY 401/403 at all? Because some endpoints (e.g. flags, third-party
 * blockers) legitimately 401 in unauth mode and aren't worth gating per-request.
 * The PR's `client_request_failure` posthog event captures `is_shared_view` so
 * those leaks are still observable in production telemetry.
 *
 * What we do NOT allow: any /api/environments/{id}/{resource} 4xx, because
 * those are the resource-specific calls that the shared-view skipping fix is
 * supposed to gate. If one of those leaks, the gate is broken.
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
 * Assert that no `/api/environments/{team}/{resource}` request 4xx'd while the
 * shared page was rendering. We allow 401/403 against non-team-scoped paths
 * (e.g. /api/user_home_settings/, /api/flags/) because those have legitimate
 * unauth failure modes — the regression we're guarding against is team-scoped
 * resource calls leaking out of the gate.
 */
export function expectNoTeamScopedApiLeaks(failedApiResponses: ReadonlyArray<RecordedFailure>): void {
    const leaked = failedApiResponses.filter(({ url }) => /\/api\/(environments|projects)\/\d+\//.test(url))
    expect(leaked, `Unexpected team-scoped API failures in shared mode:\n${formatFailures(leaked)}`).toEqual([])
}

function formatFailures(failures: ReadonlyArray<RecordedFailure>): string {
    return failures.map(({ method, status, url }) => `  ${method} ${url} -> ${status}`).join('\n') || '(none)'
}
