import { Page } from '@playwright/test'
import fs from 'fs'
import path from 'path'

import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

type BillingRouteHandlers = {
    getResponse: (billingContent: Record<string, any>) => Record<string, any>
    patchResponse: (billingContent: Record<string, any>, requestBody: Record<string, any>) => Record<string, any>
    /** Awaited after a PATCH is applied but before its response is sent — lets a test hold a response in flight. */
    beforePatchResponse?: (requestBody: Record<string, any>) => Promise<void> | void
}

async function setupBillingRoutes(page: Page, handlers: BillingRouteHandlers): Promise<void> {
    const filePath = path.join(__dirname, '../../mocks/billing/billing.json')
    let billingContent = JSON.parse(fs.readFileSync(filePath, 'utf-8'))
    let isInitialized = false

    await page.route('**/api/billing/', async (route) => {
        const method = route.request().method()

        if (method === 'GET') {
            // Only apply getResponse transformation on first GET request.
            // This prevents the mock from resetting to initial state after a PATCH update.
            // Without this, the second GET after form submission would reset the limit back to initial value.
            if (!isInitialized) {
                billingContent = handlers.getResponse(billingContent)
                isInitialized = true
            }
            await route.fulfill({
                status: 200,
                body: JSON.stringify(billingContent),
                headers: {
                    'X-Mock-Response': 'true',
                },
            })
        } else if (method === 'PATCH') {
            const requestBody = route.request().postDataJSON() ?? {}
            billingContent = handlers.patchResponse(billingContent, requestBody)
            // Snapshot before the gate so a held response echoes the state at commit time, like a real slow server.
            const responseBody = JSON.stringify(billingContent)
            await handlers.beforePatchResponse?.(requestBody)
            await route.fulfill({
                status: 200,
                body: responseBody,
                headers: {
                    'X-Mock-Response': 'true',
                },
            })
        }
    })
}

test.describe('Billing Limits', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ skip_onboarding: true, no_demo_data: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Show no limits set and allow user to set one', async ({ page }) => {
        await setupBillingRoutes(page, {
            getResponse: (billingContent) => billingContent,
            patchResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 100 }
                return billingContent
            },
        })

        await page.goto('/organization/billing')

        await page.locator('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoViewIfNeeded()
        await expect(page.locator('[data-attr="billing-limit-not-set-product_analytics"]')).toBeVisible()
        await page
            .getByTestId('billing-limit-input-wrapper-product_analytics')
            .getByRole('button', { name: 'Set a billing limit' })
            .click()
        await page.fill('[data-attr="billing-limit-input-product_analytics"]', '100')
        await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()

        // Wait for form to exit edit mode (indicates async flow completed)
        await expect(page.locator('[data-attr="save-billing-limit-product_analytics"]')).not.toBeVisible()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
            'You have a $100 billing limit set'
        )
    })

    test('Show existing limit and allow user to change it', async ({ page }) => {
        await setupBillingRoutes(page, {
            getResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 100 }
                return billingContent
            },
            patchResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 200 }
                return billingContent
            },
        })

        await page.goto('/organization/billing')

        await page.locator('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoViewIfNeeded()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toBeVisible()
        await page.locator('text=Edit limit').click()
        await page.fill('[data-attr="billing-limit-input-product_analytics"]', '200')
        await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()

        // Wait for form to exit edit mode (indicates async flow completed)
        await expect(page.locator('[data-attr="save-billing-limit-product_analytics"]')).not.toBeVisible()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
            'You have a $200 billing limit set'
        )
    })

    test('Show existing limit and allow user to change set to $0', async ({ page }) => {
        await setupBillingRoutes(page, {
            getResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 100 }
                return billingContent
            },
            patchResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 0 }
                return billingContent
            },
        })

        await page.goto('/organization/billing')

        await page.locator('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoViewIfNeeded()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toBeVisible()
        await page.locator('text=Edit limit').click()
        await page.fill('[data-attr="billing-limit-input-product_analytics"]', '0')
        await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()

        // Wait for form to exit edit mode (indicates async flow completed)
        await expect(page.locator('[data-attr="save-billing-limit-product_analytics"]')).not.toBeVisible()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
            'You have a $0 billing limit set'
        )
    })

    test('Show existing limit and allow user to remove it', async ({ page }) => {
        await setupBillingRoutes(page, {
            getResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 100 }
                return billingContent
            },
            patchResponse: (billingContent) => {
                billingContent.custom_limits_usd = {}
                return billingContent
            },
        })

        await page.goto('/organization/billing')

        await page.locator('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoViewIfNeeded()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toBeVisible()
        await page.locator('text=Edit limit').click()
        await page.locator('[data-attr="remove-billing-limit-product_analytics"]').click()

        await expect(page.locator('[data-attr="billing-limit-not-set-product_analytics"]')).toBeVisible()
    })

    test("Saving one product's limit does not lock or clear another product's editor", async ({ page }) => {
        let releaseAnalyticsResponse: () => void = () => {}
        const analyticsResponseGate = new Promise<void>((resolve) => (releaseAnalyticsResponse = resolve))

        await setupBillingRoutes(page, {
            getResponse: (billingContent) => billingContent,
            patchResponse: (billingContent, requestBody) => {
                billingContent.custom_limits_usd = {
                    ...billingContent.custom_limits_usd,
                    ...requestBody.custom_limits_usd,
                }
                return billingContent
            },
            beforePatchResponse: (requestBody) =>
                'product_analytics' in (requestBody.custom_limits_usd ?? {}) ? analyticsResponseGate : undefined,
        })

        await page.goto('/organization/billing')

        const analytics = page.getByTestId('billing-limit-input-wrapper-product_analytics')
        const replay = page.getByTestId('billing-limit-input-wrapper-session_replay')

        await test.step('open both editors and type a value in each', async () => {
            await analytics.scrollIntoViewIfNeeded()
            await analytics.getByRole('button', { name: 'Set a billing limit' }).click()
            await page.fill('[data-attr="billing-limit-input-product_analytics"]', '100')
            await replay.scrollIntoViewIfNeeded()
            await replay.getByRole('button', { name: 'Set a billing limit' }).click()
            await page.fill('[data-attr="billing-limit-input-session_replay"]', '150')
        })

        await test.step("while one save is in flight, the other product's editor stays usable", async () => {
            await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()
            // The gated response holds this save in flight: its own input locks...
            await expect(page.locator('[data-attr="billing-limit-input-product_analytics"]')).toBeDisabled()
            // ...but the other product's editor must stay enabled with its typed value intact
            await expect(page.locator('[data-attr="billing-limit-input-session_replay"]')).toBeEnabled()
            await expect(page.locator('[data-attr="billing-limit-input-session_replay"]')).toHaveValue('150')
        })

        await test.step("completing the save closes only that product's editor", async () => {
            releaseAnalyticsResponse()
            await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
                'You have a $100 billing limit set'
            )
            await expect(page.locator('[data-attr="billing-limit-input-session_replay"]')).toHaveValue('150')
        })

        await test.step('the untouched editor still saves normally', async () => {
            await page.locator('[data-attr="save-billing-limit-session_replay"]').click()
            await expect(page.locator('[data-attr="billing-limit-set-session_replay"]')).toContainText(
                'You have a $150 billing limit set'
            )
            await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
                'You have a $100 billing limit set'
            )
        })
    })

    test('Warns before saving a limit below current or projected usage', async ({ page }) => {
        await setupBillingRoutes(page, {
            getResponse: (billingContent) => {
                const analytics = billingContent.products.find((p: any) => p.type === 'product_analytics')
                analytics.current_amount_usd = '100.00'
                analytics.projected_amount_usd = '150.00'
                billingContent.next_period_custom_limits_usd = {}
                return billingContent
            },
            patchResponse: (billingContent, requestBody) => {
                // Model the real API: a limit below current spend is clamped to that spend
                // for this period and the requested value is deferred to the next period.
                for (const [key, value] of Object.entries<number>(requestBody.custom_limits_usd ?? {})) {
                    if (value < 100) {
                        billingContent.custom_limits_usd[key] = 100
                        billingContent.next_period_custom_limits_usd[key] = value
                    } else {
                        billingContent.custom_limits_usd[key] = value
                    }
                }
                return billingContent
            },
        })

        await page.goto('/organization/billing')

        const analytics = page.getByTestId('billing-limit-input-wrapper-product_analytics')
        await analytics.scrollIntoViewIfNeeded()
        await analytics.getByRole('button', { name: 'Set a billing limit' }).click()

        await test.step('cancelling the below-usage warning saves nothing and keeps the editor open', async () => {
            await page.fill('[data-attr="billing-limit-input-product_analytics"]', '50')
            await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()
            await expect(page.locator('.LemonModal')).toContainText('below your current usage')
            await page.getByRole('button', { name: 'No, I changed my mind' }).click()
            await expect(page.locator('.LemonModal')).not.toBeVisible()
            await expect(page.locator('[data-attr="billing-limit-input-product_analytics"]')).toHaveValue('50')
        })

        await test.step('confirming clamps this period to usage and defers the limit to next period', async () => {
            await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()
            await page.getByRole('button', { name: 'Yes, I understand' }).click()
            await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
                'You have a $100 billing limit set'
            )
            await expect(analytics).toContainText('Your limit for next period: $50')
            await expect(page.locator('[data-attr="remove-billing-limit-next-period-product_analytics"]')).toBeVisible()
        })

        await test.step('a limit below projected (but above current) usage warns about throttling', async () => {
            await analytics.getByRole('button', { name: 'Edit limit' }).click()
            await page.fill('[data-attr="billing-limit-input-product_analytics"]', '120')
            await page.locator('[data-attr="save-billing-limit-product_analytics"]').click()
            await expect(page.locator('.LemonModal')).toContainText('predicted usage is above your billing limit')
            await page.getByRole('button', { name: 'Yes, I understand' }).click()
            await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toContainText(
                'You have a $120 billing limit set'
            )
        })
    })
})
