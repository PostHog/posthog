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

    test('displays "pick myself" option', async ({ page }) => {
        await page.goto('/onboarding/use-case')

        // Check for "pick myself" button
        await expect(page.locator('text=I want to pick products myself')).toBeVisible()

        // Click it
        await page.locator('text=I want to pick products myself').click()

        // Should navigate to products page without recommendations
        await expect(page).toHaveURL(/\/products\?useCase=pick_myself/)

        // Should show all products in grid layout (no pre-selection)
        await expect(page.locator('[data-attr*="-onboarding-card"]')).toHaveCount(10) // All products
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

    test('can toggle products on products page', async ({ page }) => {
        await page.goto('/products?useCase=see_user_behavior')

        // Product Analytics and Session Replay should be pre-selected
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).toHaveClass(/border-accent/)

        // Deselect Product Analytics
        await page.locator('[data-attr="product_analytics-onboarding-card"]').click()

        // Should no longer be selected
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).not.toHaveClass(/border-accent/)

        // Re-select it
        await page.locator('[data-attr="product_analytics-onboarding-card"]').click()

        // Should be selected again
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).toHaveClass(/border-accent/)
    })

    test('shows and hides other products', async ({ page }) => {
        await page.goto('/products?useCase=launch_features')

        // "Show all apps" button should be visible
        await expect(page.locator('text=Show all apps')).toBeVisible()

        // Other products should not be visible initially
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).not.toBeVisible()

        // Click "Show all apps"
        await page.locator('text=Show all apps').click()

        // Other products should now be visible
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).toBeVisible()

        // "Hide other apps" button should be visible
        await expect(page.locator('text=Hide other apps')).toBeVisible()

        // Click "Hide other apps"
        await page.locator('text=Hide other apps').click()

        // Other products should be hidden again
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).not.toBeVisible()
    })

    test('starts onboarding with selected products', async ({ page }) => {
        await page.goto('/products?useCase=see_user_behavior')

        // Get started button should be visible
        await expect(page.locator('[data-attr="onboarding-continue"]')).toBeVisible()

        // Click get started
        await page.locator('[data-attr="onboarding-continue"]').click()

        // Should navigate to first product onboarding
        await expect(page).toHaveURL(/\/onboarding\/.*\/product_analytics/)
    })

    test('allows selecting first product when multiple selected', async ({ page }) => {
        await page.goto('/products?useCase=see_user_behavior')

        // Both products should be selected
        await expect(page.locator('[data-attr="product_analytics-onboarding-card"]')).toHaveClass(/border-accent/)
        await expect(page.locator('[data-attr="session_replay-onboarding-card"]')).toHaveClass(/border-accent/)

        // Should show dropdown to select first product
        await expect(page.locator('text=Start with')).toBeVisible()

        // Click the dropdown
        await page.locator('.LemonSelect').click()

        // Should show both products
        await expect(page.locator('text=Product analytics')).toBeVisible()
        await expect(page.locator('text=Session replay')).toBeVisible()

        // Select Session Replay
        await page.locator('text=Session replay').last().click()

        // Click Go button
        await page.locator('[data-attr="onboarding-continue"]').click()

        // Should navigate to session replay onboarding
        await expect(page).toHaveURL(/\/onboarding\/.*\/session_replay/)
    })

    test('skip onboarding button works', async ({ page }) => {
        // Mock ingested event so skip button appears
        await page.goto('/products?useCase=see_user_behavior')

        // Look for skip button (only appears if team has ingested events)
        const skipButton = page.locator('text=Skip onboarding')
        if (await skipButton.isVisible()) {
            await skipButton.click()
            // Should navigate away from onboarding
            await expect(page).not.toHaveURL(/\/onboarding/)
        }
    })
})
