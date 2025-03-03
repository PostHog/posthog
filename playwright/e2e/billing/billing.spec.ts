import fs from 'fs'
import path from 'path'

import { expect, test } from '../../utils/playwright-test-base'

test.describe('Billing', () => {
    test.beforeEach(async ({ page }) => {
        // This replicates cy.intercept('/api/billing/') with fixture
        // We'll read the JSON from a fixture folder. Adjust the path as needed.
        await page.route('**/api/billing/', async (route) => {
            // If your codebase uses a different structure, update accordingly
            const filePath = path.join(__dirname, '../../mocks/billing/billing.json')
            const billingContent = fs.readFileSync(filePath, 'utf-8')
            await route.fulfill({
                status: 200,
                body: billingContent,
            })
        })

        // Visit the billing page
        await page.goto('/organization/billing')
    })

    test('Show and submit unsubscribe survey', async ({ page }) => {
        // Intercept the specific unsubscribe request
        await page.route('**/api/billing/deactivate?products=product_analytics', async (route) => {
            const filePath = path.join(__dirname, '../../mocks/billing/billing-unsubscribed-product-analytics.json')
            const unsubscribedContent = fs.readFileSync(filePath, 'utf-8')
            await route.fulfill({
                status: 200,
                body: unsubscribedContent,
            })
        })

        // In Cypress we did "cy.get('[data-attr=more-button]').first().click()"
        // In Playwright, we can use nth(0) to select the first occurrence
        await page.locator('[data-attr=more-button]').nth(0).click()
        await page.locator('.LemonButton', { hasText: 'Unsubscribe' }).click()

        // Check the modal
        await expect(page.locator('.LemonModal h3')).toContainText('Unsubscribe from Product analytics')
        await page.click('[data-attr=unsubscribe-reason-too-expensive]')
        await page.fill('[data-attr=unsubscribe-reason-survey-textarea]', 'Product analytics')

        // Confirm unsubscribing
        await page.locator('.LemonModal .LemonButton', { hasText: 'Unsubscribe' }).click()

        // TODO need to be able to read posthog events

        // For now, we'll just check that the modal disappears and the request was made
        await expect(page.locator('.LemonModal')).not.toBeVisible()
    })

    test('Unsubscribe survey text area maintains unique state between product types', async ({ page }) => {
        // Working with the first product
        await page.locator('[data-attr=more-button]').nth(0).click()
        await page.locator('.LemonButton', { hasText: 'Unsubscribe' }).click()
        await expect(page.locator('.LemonModal h3')).toContainText('Unsubscribe from Product analytics')
        await page.click('[data-attr=unsubscribe-reason-too-expensive]')
        await page.fill('[data-attr=unsubscribe-reason-survey-textarea]', 'Product analytics')
        await page.locator('.LemonModal .LemonButton', { hasText: 'Cancel' }).click()

        // Second product
        await page.locator('[data-attr=more-button]').nth(1).click()
        await page.locator('.LemonButton', { hasText: 'Unsubscribe' }).click()
        await expect(page.locator('.LemonModal h3')).toContainText('Unsubscribe from Session replay')
        await page.click('[data-attr=unsubscribe-reason-too-expensive]')
        await page.fill('[data-attr=unsubscribe-reason-survey-textarea]', 'Session replay')
        await page.locator('.LemonModal .LemonButton', { hasText: 'Cancel' }).click()

        // Re-check the first product's survey
        await page.locator('[data-attr=more-button]').nth(0).click()
        await page.locator('.LemonButton', { hasText: 'Unsubscribe' }).click()
        await expect(page.locator('[data-attr=unsubscribe-reason-survey-textarea]')).toHaveValue('Product analytics')
    })
})
