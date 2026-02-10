import { waitForPageLoaded } from '../utils/navigation'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Annotations', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('datamanagement')
        await page.goToMenuItem('annotations')
        await waitForPageLoaded(page)
    })

    test('Annotations loaded', async ({ page }) => {
        // Check that the annotations page loaded with key elements visible
        await expect(page.getByRole('heading', { name: 'Annotations' })).toBeVisible()
        await expect(page.getByRole('button', { name: 'New annotation' })).toBeVisible()
        await expect(page.locator('[data-attr="annotations-content"]')).toBeVisible()
    })

    test('Create annotation', async ({ page }) => {
        // Wait for the create button to be visible before clicking
        // await expect(page.locator('[data-attr=create-annotation]')).toBeEnabled()
        const createAnnotationButton = page.getByRole('button', { name: 'New annotation' })
        await expect(createAnnotationButton).toBeEnabled()
        await createAnnotationButton.click()

        // Use a unique name to avoid conflicts with retries
        const uniqueAnnotationName = `Test Annotation ${Date.now()}`
        await page.fill('[data-attr=create-annotation-input]', uniqueAnnotationName)
        await page.click('[data-attr=create-annotation-submit]')
        await expect(page.locator('[data-attr=annotations-table]')).toContainText(uniqueAnnotationName)
    })
})
