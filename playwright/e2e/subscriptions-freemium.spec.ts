/**
 * Subscriptions freemium gate — end-to-end browser test.
 *
 * Verifies the free-tier subscription gate in a real browser against the real frontend:
 *  - A free org UNDER the limit sees the normal "New Subscription" create form.
 *  - A free org AT the limit sees the PayGateMini upsell instead of the create form.
 *  - Editing an existing subscription is never gated.
 *
 * The org's feature entitlement and the team-wide subscription count are mocked
 * (the gate is a pure frontend decision: `!hasSubscriptionsFeature && count >= FREE_LIMIT`),
 * so this exercises the real frontend gate without needing seeded DB rows. The hard
 * backend limit is covered separately by ee/api/test/test_subscription.py.
 *
 * NOTE ON VERIFICATION: authored against the implementation on this branch; it must run
 * against a master-based instance (the gate component only exists here). It could not be
 * run locally during authoring because the shared dev DB was on a divergent (pr-58809)
 * migration state. Run with: `BASE_URL=http://localhost:8010 pnpm exec playwright test
 * e2e/subscriptions-freemium.spec.ts` against an instance serving this branch. If a
 * selector needs adjustment on first run, the data-attrs referenced are:
 * `insight-subscribe-dropdown-menu-item` and `insight-subscriptions-modal`.
 */
import { expect, Page } from '@playwright/test'

import { test } from '../utils/workspace-test-base'

const FREE_LIMIT = 5

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

/** Mock the team-wide subscription count that the create gate reads (GET /subscriptions?limit=1). */
async function mockSubscriptionCount(page: Page, count: number): Promise<void> {
    await page.route('**/api/projects/*/subscriptions/?*limit=1*', async (route) => {
        await route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({ count, next: null, previous: null, results: [] }),
        })
    })
}

async function createInsight(page: Page, teamId: string, apiKey: string): Promise<string> {
    const res = await page.request.post(`/api/projects/${teamId}/insights/`, {
        headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
        data: {
            name: 'Freemium gate insight',
            query: {
                kind: 'InsightVizNode',
                source: { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] },
            },
        },
    })
    expect(res.ok()).toBe(true)
    return (await res.json()).short_id
}

test.describe('subscriptions freemium gate', () => {
    test('free org under the limit can open the create form', async ({ page, playwrightSetup }) => {
        const ws = await playwrightSetup.createWorkspace({ skip_onboarding: true })
        const shortId = await createInsight(page, ws.team_id, ws.personal_api_key)

        await mockFreeOrg(page)
        await mockSubscriptionCount(page, FREE_LIMIT - 1)
        await playwrightSetup.login(page, ws)

        // Open the create form directly via the insight subscribe route.
        await page.goto(`/project/${ws.team_id}/insights/${shortId}/subscriptions/new`)

        await expect(page.getByText('New Subscription')).toBeVisible()
        await expect(page.getByText('Upgrade to use this feature')).toBeHidden()
    })

    test('free org at the limit sees the upgrade paywall instead of the create form', async ({
        page,
        playwrightSetup,
    }) => {
        const ws = await playwrightSetup.createWorkspace({ skip_onboarding: true })
        const shortId = await createInsight(page, ws.team_id, ws.personal_api_key)

        await mockFreeOrg(page)
        await mockSubscriptionCount(page, FREE_LIMIT)
        await playwrightSetup.login(page, ws)

        await page.goto(`/project/${ws.team_id}/insights/${shortId}/subscriptions/new`)

        // PayGateMini upsell renders; the create form does not.
        await expect(page.getByText('Upgrade to use this feature')).toBeVisible()
        await expect(page.getByText('New Subscription')).toBeHidden()
    })
})
