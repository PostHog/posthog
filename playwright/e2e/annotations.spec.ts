import { expect, test } from '../utils/playwright-test-base'

test.describe('Annotations', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('datamanagement')
        await page.goToMenuItem('annotations')
    })

    test('Annotations loaded', async ({ page }) => {
        // Check that the annotations page loaded with key elements visible
        await expect(page.getByRole('heading', { name: 'Annotations' })).toBeVisible()
        await expect(page.getByRole('button', { name: 'New annotation' })).toBeVisible()
        await expect(page.locator('[data-attr="annotations-content"]')).toBeVisible()
    })

    test('Create annotation', async ({ page }) => {
        // Wait for the create button to be visible before clicking
        const createButton = page.locator('[data-attr=create-annotation]')
        await expect(createButton).toBeVisible({ timeout: 10000 })
        await createButton.click()

        // Wait for the modal to open and input to be visible
        const annotationInput = page.locator('[data-attr=create-annotation-input]')
        await expect(annotationInput).toBeVisible({ timeout: 5000 })

        // Use a unique name to avoid conflicts with retries
        const uniqueAnnotationName = `Test Annotation ${Date.now()}`
        await annotationInput.fill(uniqueAnnotationName)

        // Click submit and wait for the annotation to appear
        const submitButton = page.locator('[data-attr=create-annotation-submit]')
        await expect(submitButton).toBeVisible()
        await submitButton.click()

        // Wait for the table to contain the new annotation
        await expect(page.locator('[data-attr=annotations-table]')).toContainText(uniqueAnnotationName, {
            timeout: 10000,
        })
    })
})
