import { delay } from 'lib/utils'

import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Early Access Management', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/early_access_features')
    })

    test('Early access feature new and list', async ({ page }) => {
        // load an empty early access feature page
        await expect(page.locator('h1')).toContainText('Early access features')
        await expect(page).toHaveTitle('Early access features • PostHog')

        // go to create a new feature
        await page.getByRole('link', { name: 'New feature' }).click()

        // cancel new feature
        await page.locator('[data-attr="cancel-feature"]').click()
        await expect(page.locator('h1')).toContainText('Early access features')

        const name = randomString('test-feature')

        // set feature name & description
        await page.getByRole('link', { name: 'New feature' }).click()
        await page.click('[data-attr="scene-title-textarea"]')
        await page.locator('[data-attr="scene-title-textarea"]').pressSequentially(name)
        await delay(1000)
        await expect(page.locator('[data-attr="save-feature"]')).toContainText('Save as draft')

        // save
        await page.locator('[data-attr="save-feature"]').click()
        await expect(page.locator('[data-attr="success-toast"]')).toContainText('Early access feature saved')

        // back to features
        await page.goto('/early_access_features')
        await expect(page.locator('tbody')).toContainText(name)

        // edit feature
        await page.locator('a.Link', { hasText: name }).click()
        await page.locator('[data-attr="edit-feature"]').click()
        await expect(page.locator('[data-attr="scene-title-textarea"]')).toContainText(name)
        await expect(page.locator('[data-attr="save-feature"]')).toContainText('Save')

        // delete feature
        await page.locator('[data-attr="info-actions-panel"]').click()
        await page.locator('[data-attr="early-access-feature-delete"]').click()
        await expect(page.getByRole('heading', { name: 'Permanently delete feature?' })).toBeVisible()
        await page.locator('[data-attr="confirm-delete-feature"]').click()
        await expect(page.locator('[data-attr=info-toast]')).toContainText(
            'Early access feature deleted. Remember to delete corresponding feature flag if necessary'
        )
    })
})
