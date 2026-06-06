import { Page } from '@playwright/test'
import fs from 'fs'
import path from 'path'

import { expect, test } from '../../utils/playwright-test-base'

type BillingRouteHandlers = {
    getResponse: (billingContent: Record<string, any>) => Record<string, any>
    patchResponse: (billingContent: Record<string, any>) => Record<string, any>
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
            billingContent = handlers.patchResponse(billingContent)
            await route.fulfill({
                status: 200,
                body: JSON.stringify(billingContent),
                headers: {
                    'X-Mock-Response': 'true',
                },
            })
        }
    })
}

test.describe('Billing Limits', () => {
    test.skip('Show no limits set and allow user to set one', async ({ page }) => {
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

    test.skip('Show existing limit and allow user to remove it', async ({ page }) => {
        await setupBillingRoutes(page, {
            getResponse: (billingContent) => {
                billingContent.custom_limits_usd = { product_analytics: 100 }
                return billingContent
            },
            patchResponse: (billingContent) => billingContent,
        })

        await page.goto('/organization/billing')

        await page.locator('[data-attr="billing-limit-input-wrapper-product_analytics"]').scrollIntoViewIfNeeded()
        await expect(page.locator('[data-attr="billing-limit-set-product_analytics"]')).toBeVisible()
        await page.locator('text=Edit limit').click()
        await page.locator('[data-attr="remove-billing-limit-product_analytics"]').click()
        await expect(page.locator('[data-attr="billing-limit-not-set-product_analytics"]')).toBeVisible()
    })
})
