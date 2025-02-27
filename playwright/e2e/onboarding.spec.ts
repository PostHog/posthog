import { expect, test } from '../utils/playwright-test-base'

test.describe('Onboarding', () => {
    test.beforeEach(async () => {
        // enable 'product-intro-pages' or so
    })

    test('Navigate from /products to /onboarding to a product intro page', async ({ page }) => {
        await page.goto('/products')
        await page.locator('[data-attr=product_analytics-onboarding-card]').click()

        await page.locator('[data-attr=onboarding-continue]').click()
        await expect(page.locator('[data-attr=onboarding-breadcrumbs] > :first-child')).not.toContainText(
            'Product intro'
        )

        // skip some steps
        await page.goto('/insights') // or something that triggers 'product-intro' if incomplete

        await expect(page.locator('[data-attr=top-bar-name] >> span')).toContainText('Onboarding')
        await expect(page.locator('[data-attr=product-intro-title]')).toContainText(
            'Product analytics with autocapture'
        )
        await expect(page.locator('[data-attr=start-onboarding]')).toBeVisible()
        await expect(page.locator('[data-attr=skip-onboarding]')).toHaveCount(0)
    })
})
