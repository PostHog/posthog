import { expect, test } from '../utils/playwright-test-base'

test.describe('Annotations', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('datamanagement')
        await page.goToMenuItem('annotations')
    })

    test('Annotations loaded', async ({ page }) => {
        await expect(page.getByTestId('product-introduction-annotation')).toBeVisible()
        await expect(page.locator('[data-attr="product-introduction-docs-link"]')).toContainText('Learn more')
    })

    test('Create annotation', async ({ page }) => {
        await page.click('[data-attr=create-annotation]')
        await page.fill('[data-attr=create-annotation-input]', 'Test Annotation')
        await page.click('[data-attr=create-annotation-submit]')
        await expect(page.locator('[data-attr=annotations-table]')).toContainText('Test Annotation')
        await expect(page.locator('text=Create your first annotation')).not.toBeVisible()
    })
})
