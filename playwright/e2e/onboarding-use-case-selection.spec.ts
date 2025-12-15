import { expect, test } from '../utils/playwright-test-base'

test.describe('Use Case Selection Onboarding', () => {
    test.beforeEach(async ({ page, request }) => {
        // Reset onboarding state
        await request.patch('/api/projects/1/', {
            data: { completed_snippet_onboarding: false },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })

        // Enable the feature flag
        await page.goto('/home')
        await page.evaluate(() => {
            window.posthog?.featureFlags?.override({ 'onboarding-use-case-selection': true })
        })
    })

    test.afterAll(async ({ request }) => {
        await request.patch('/api/projects/1/', {
            data: { completed_snippet_onboarding: true },
            headers: { Authorization: 'Bearer e2e_demo_api_key' },
        })
    })

    test('displays use case selection page', async ({ page }) => {
        await page.goto('/onboarding/use-case')

        // Check for main heading
        await expect(page.locator('h1')).toContainText('What do you want to do with PostHog?')

        // Check for specific use cases
        await expect(page.locator('text=Understand how users behave')).toBeVisible()
        await expect(page.locator('text=Find and fix issues')).toBeVisible()
        await expect(page.locator('text=Launch features with confidence')).toBeVisible()
        await expect(page.locator('text=Collect user feedback')).toBeVisible()
        await expect(page.locator('text=Monitor AI applications')).toBeVisible()
    })

    test('selects a use case and navigates to products page', async ({ page }) => {
        await page.goto('/onboarding/use-case')

        // Click on "Understand how users behave" use case
        await page.locator('text=Understand how users behave').click()

        // Should navigate to products page with useCase param
        await expect(page).toHaveURL(/\/products\?useCase=see_user_behavior/)

        // Should show recommended products pre-selected
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).toHaveClass(/border-accent/)
        await expect(page.locator('[data-attr="session_replay-onboarding-card"]')).toHaveClass(/border-accent/)
    })

    test('products page shows back button with use case selection', async ({ page }) => {
        await page.goto('/products?useCase=fix_issues')

        // Back button should be visible
        await expect(page.locator('text=Go back to change my goal')).toBeVisible()

        // Click back button
        await page.locator('text=Go back to change my goal').click()

        // Should navigate back to use case selection
        await expect(page).toHaveURL(/\/onboarding\/use-case/)
    })
})
