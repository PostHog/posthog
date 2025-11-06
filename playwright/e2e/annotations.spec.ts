import { expect, test } from '../utils/playwright-test-base'

test.describe('Annotations', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('datamanagement')
        await page.goToMenuItem('annotations')
    })

    test('Annotations loaded', async ({ page }) => {
        // Check that the annotations page loaded with key elements visible
        await expect(page.getByText('Annotations')).toBeVisible()
        await expect(page.getByRole('button', { name: 'New annotation' })).toBeVisible()
        await expect(page.locator('[data-attr="annotations-content"]')).toBeVisible()
    })

    test('Create annotation', async ({ page }) => {
        // Wait for the create button to be visible before clicking
        await expect(page.locator('[data-attr=create-annotation]')).toBeVisible()
        await page.click('[data-attr=create-annotation]')

        // Use a unique name to avoid conflicts with retries
        const uniqueAnnotationName = `Test Annotation ${Date.now()}`
        await page.fill('[data-attr=create-annotation-input]', uniqueAnnotationName)
        await page.click('[data-attr=create-annotation-submit]')
        await expect(page.locator('[data-attr=annotations-table]')).toContainText(uniqueAnnotationName)
    })
})
