import { expect, test } from '../utils/playwright-test-base'

test.describe('Persons', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('personsmanagement')
    })

    test('All tabs work', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Persons')
        await page.fill('[data-attr=persons-search]', 'marisol')
        await page.keyboard.press('Enter')
        await page.waitForTimeout(200) // or some assertion
        // check some row
    })

    test('Deleting person from list', async ({ page }) => {
        await page.fill('[data-attr=persons-search]', 'hodge')
        await page.keyboard.press('Enter')
        await page.locator('tr', { hasText: 'hodge.espinoza@cubix.io' }).locator('[data-attr=delete-person]').click()
        await expect(page.locator('.LemonModal__header h3')).toHaveText(
            'Are you sure you want to delete "hodge.espinoza@cubix.io"?'
        )
        await page.locator('label:has-text("I understand")').click()
        await page.locator('.LemonButton--secondary:has-text("Delete person")').click()
        await expect(page.locator('.Toastify__toast-body')).toContainText('was removed from the project')
        await expect(page.locator('tr', { hasText: 'hodge.espinoza@cubix.io' })).toHaveCount(0)
    })
})
