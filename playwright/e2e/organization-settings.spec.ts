import { expect, test } from '../utils/playwright-test-base'

test.describe('Organization settings', () => {
    test.beforeEach(async ({ page }) => {
        // intercept /api/billing/ with fixture "billing.json" maybe
        await page.goToMenuItem('me')
        await page.locator('[data-attr=top-menu-item-org-settings]').click()
        await expect(page).toHaveURL(/settings\/organization/)
    })

    test('can create a new organization', async ({ page }) => {
        await page.locator('[data-attr=breadcrumb-organization]').click()
        await page.locator('[data-attr=new-organization-button]').click()
        await page.fill('[data-attr=organization-name-input]', 'New Organization')
        await page.click('[data-attr=create-organization-ok]')
        await expect(page.locator('[data-attr=organization-name-input-settings]')).toHaveValue('New Organization')
    })

    test('can delete an organization', async ({ page }) => {
        await expect(page.locator('[data-attr=organization-name-input-settings]')).toHaveValue('New Organization')
        await page.locator('[data-attr=delete-organization-button]').click()
        await page.locator('[data-attr=delete-organization-confirmation-input]').fill('New Organization')
        await page.click('[data-attr=delete-organization-ok]')
        // Should redirect to / after
        await expect(page.locator('[data-attr=organization-name-input-settings]')).toHaveCount(0)
        await expect(page.locator('[data-attr=top-bar-name]')).toContainText('Homepage')
    })
})
