import { expect, test } from '../../utils/playwright-test-base'

test.describe('Billing Upgrade CTA', () => {
    test.beforeEach(async ({ page }) => {
        // intercept /api/billing/ with fixture "unsubscribed"
        await page.route('/api/billing/', async (route) => {
            await route.fulfill({
                status: 200,
                body: JSON.stringify({
                    // from "api/billing/billing-unsubscribed.json"
                    // or do a partial
                    custom_limits_usd: {},
                    has_active_subscription: false,
                }),
            })
        })
    })

    test('Check that events are being sent on each page visit', async ({ page }) => {
        await page.goto('/organization/billing')
        await expect(page.locator('[data-attr=billing-page-core-upgrade-cta] .LemonButton__content')).toHaveText(
            'Upgrade now'
        )
        // if we store events in window._cypress_posthog_captures, we'd do something akin to check them
        // e.g. you might do:
        // const events = ...
        // const matchingEvents = events.filter(...)

        // Then reload with a fixture "subscription"
        await page.route('/api/billing/', async (route) => {
            await route.fulfill({
                status: 200,
                body: JSON.stringify({
                    has_active_subscription: true,
                    plan: 'free',
                    // etc.
                }),
            })
        })
        await page.reload()

        await expect(page.locator('[data-attr=billing-page-core-upgrade-cta] .LemonButton__content')).toHaveCount(0)
        await expect(page.locator('[data-attr=manage-billing]')).toHaveText('Manage card details and invoices')
    })
})
