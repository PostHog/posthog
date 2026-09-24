import { LOGIN_PASSWORD, LOGIN_USERNAME } from '@playwright-utils/playwright-test-core'
import { expect, test } from '@playwright-utils/workspace-test-base'

/**
 * Redeeming a community code on /coupons/community through a running PostHog with a billing
 * service behind it.
 *
 * Billing grants the credit only to an organization with an active subscription, a card on file,
 * and at least one paid invoice with a non-zero total. A fresh workspace has none of these, so this
 * logs in as LOGIN_USERNAME / LOGIN_PASSWORD, who must be an admin or owner of their current
 * organization, and that organization needs all three. Billing also refuses claims while the
 * community campaign is a draft, so the campaign must be active.
 *
 * CI has no billing behind the dev stack, so the suite only runs when asked:
 *
 *   RUN_BILLING_E2E=1 BASE_URL=http://localhost:8010 COMMUNITY_COUPON_E2E_CODE=COM-... \
 *     pnpm --filter=@posthog/playwright exec playwright test products/billing/frontend/e2e/community-coupon.spec.ts
 *
 * A code redeems once, and an organization redeems up to three community codes per calendar month
 * (UTC), so each run needs an unused code and an organization that has not used its three for the
 * month.
 */

const code = process.env.COMMUNITY_COUPON_E2E_CODE ?? ''

test.describe('Community coupon', () => {
    test.skip(!process.env.RUN_BILLING_E2E, 'needs a billing service behind PostHog; set RUN_BILLING_E2E=1')
    test.skip(!code, 'needs an unused community code in COMMUNITY_COUPON_E2E_CODE')

    test('an admin redeems a code and the page then shows it as claimed', async ({ page }) => {
        const login = await page.request.post('/api/login/', {
            data: { email: LOGIN_USERNAME, password: LOGIN_PASSWORD },
        })
        expect(login.ok()).toBe(true)

        await test.step('redeem the code', async () => {
            await page.goto('/coupons/community')
            // A cold dev server can take a while to serve the app shell.
            await expect(page.getByLabel('Coupon code')).toBeVisible({ timeout: 30000 })
            await page.getByLabel('Coupon code').fill(code)
            await page.getByRole('button', { name: 'Redeem coupon' }).click()
            await expect(page.getByText('Coupon redeemed successfully!')).toBeVisible()
            // The store sets each code's amount, and billing may still be retrying the credit sync.
            await expect(
                page.getByText(
                    /^\$[\d,]+(\.\d{2})? of credit (was added to your organization|will appear on your account in a few minutes)\.$/
                )
            ).toBeVisible()
        })

        await test.step('the claim is still there after a reload, and another code can be entered', async () => {
            await page.reload()
            await expect(page.getByText("You've already claimed this offer!")).toBeVisible({ timeout: 30000 })
            // Community allows more than one code, so the form stays below the claimed state.
            await expect(page.getByLabel('Coupon code')).toBeVisible()
        })
    })
})
