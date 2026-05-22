/**
 * Subscriptions freemium gate — end-to-end browser test.
 *
 * Verifies the free-tier subscription gate in a real browser against the real frontend:
 *  - A free org UNDER the limit sees the normal "New Subscription" create form.
 *  - A free org AT the limit sees the PayGateMini upsell instead of the create form.
 *
 * The org's feature entitlement and the team-wide subscription count are mocked
 * (the gate is a pure frontend decision: `!hasSubscriptionsFeature && count >= FREE_LIMIT`),
 * so this exercises the real frontend gate without seeded DB rows. The hard backend limit
 * is covered separately by ee/api/test/test_subscription.py.
 *
 * Uses the legacy auto-login base against the existing project + an existing saved insight,
 * which avoids provisioning a workspace (the setup endpoint touches ClickHouse and is flaky
 * against a long-running dev instance).
 */
import { expect, Page } from '@playwright/test'

import { test } from '../utils/playwright-test-base'

const FREE_LIMIT = 5

// PayGateMini renders this button (data-attr=`${feature}-learn-more`) when the gate is shown.
// Stable across billing gate-variants, unlike the CTA copy.
const GATE_HOOK = 'subscriptions-learn-more'

/** Force the current org to look free (no SUBSCRIPTIONS entitlement) by stripping it from /api/users/@me/. */
async function mockFreeOrg(page: Page): Promise<void> {
    await page.route('**/api/users/@me/**', async (route) => {
        const response = await route.fetch()
        const me = await response.json()
        if (me?.organization?.available_product_features) {
            me.organization.available_product_features = me.organization.available_product_features.filter(
                (f: { key?: string }) => f?.key !== 'subscriptions'
            )
        }
        await route.fulfill({ response, json: me })
    })
}

/**
 * Mock the team-wide subscription count that the create gate reads (GET /subscriptions?limit=1).
 * RegExp matcher — a glob `?` would be treated as a wildcard and never match the query separator.
 */
async function mockSubscriptionCount(page: Page, count: number): Promise<void> {
    await page.route(/\/api\/projects\/\d+\/subscriptions\/\?.*limit=1/, async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ count, next: null, previous: null, results: [] }),
        })
    })
}

async function currentTeamId(page: Page): Promise<number> {
    const project = await (await page.request.get('/api/projects/@current/')).json()
    return project.id
}

async function firstSavedInsightShortId(page: Page, teamId: number): Promise<string> {
    const res = await page.request.get(`/api/projects/${teamId}/insights/?limit=1&saved=true`)
    const data = await res.json()
    expect(data.results?.length, 'expected at least one saved insight in the demo project').toBeGreaterThan(0)
    return data.results[0].short_id
}

test.describe('subscriptions freemium gate', () => {
    test('free org under the limit can open the create form', async ({ page }) => {
        const teamId = await currentTeamId(page)
        const shortId = await firstSavedInsightShortId(page, teamId)

        await mockFreeOrg(page)
        await mockSubscriptionCount(page, FREE_LIMIT - 1)

        await page.goto(`/project/${teamId}/insights/${shortId}/subscriptions/new`)

        await expect(page.getByText('New Subscription')).toBeVisible()
        await expect(page.getByTestId(GATE_HOOK)).toBeHidden()
    })

    test('free org at the limit sees the upgrade paywall instead of the create form', async ({ page }) => {
        const teamId = await currentTeamId(page)
        const shortId = await firstSavedInsightShortId(page, teamId)

        await mockFreeOrg(page)
        await mockSubscriptionCount(page, FREE_LIMIT)

        await page.goto(`/project/${teamId}/insights/${shortId}/subscriptions/new`)

        await expect(page.getByTestId(GATE_HOOK)).toBeVisible()
        await expect(page.getByText('New Subscription')).toBeHidden()
    })
})
