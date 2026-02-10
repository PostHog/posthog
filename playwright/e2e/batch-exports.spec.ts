import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Batch Exports', () => {
    test('Create new S3 batch export', async ({ page }) => {
        const name = randomString('S3 Export')

        await page.goto('/pipeline/batch-exports/new/s3')
        await expect(page.locator('h1')).toContainText('S3')

        await page.click('[data-attr="scene-title-textarea"]')
        await page.locator('[data-attr="scene-title-textarea"]').fill(name)

        await page.locator('[data-attr="batch-export-bucket-name"]').fill('my-test-bucket')
        await page.locator('[data-attr="batch-export-region"]').fill('us-east-1')
        await page.locator('[data-attr="batch-export-prefix"]').fill('events/')
        await page.locator('[data-attr="batch-export-aws-access-key-id"]').fill('AKIAIOSFODNN7EXAMPLE')
        await page
            .locator('[data-attr="batch-export-aws-secret-access-key"]')
            .fill('wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY')

        await page.locator('[data-attr="batch-export-save"]').click()
        await expect(page.locator('[data-attr="success-toast"]')).toContainText('Batch export created successfully')
    })

    test('Validate required fields prevent save', async ({ page }) => {
        await page.goto('/pipeline/batch-exports/new/s3')
        await expect(page.locator('h1')).toContainText('S3')

        await page.locator('[data-attr="batch-export-save"]').click()

        // Form should not navigate away - we should still be on the new export page
        await expect(page).toHaveURL(/\/pipeline\/batch-exports\/new\/s3/)
    })
})
