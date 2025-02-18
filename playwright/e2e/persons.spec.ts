import { test, expect } from '../utils/playwright-test-base'

test.describe('Persons', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('personsmanagement')
    })

    test('All tabs work', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Persons')
        await page.locator('[data-attr=persons-search]').fill('marisol')
        await page.keyboard.press('Enter')
        await expect(page.locator('[data-attr=persons-search]')).toHaveValue('marisol')

        await expect
            .poll(async () => {
                return await page.locator('[data-row-key]').count()
            })
            .toBeGreaterThan(1)
    })

    test('Deleting person from list', async ({ page }) => {
        await page.locator('[data-attr=persons-search]').fill('hodge')
        await page.keyboard.press('Enter')
        await page.locator('tr', { hasText: 'hodge.espinoza@cubix.io' }).locator('[data-attr=delete-person]').click()

        await expect(page.locator('.LemonModal__header h3')).toHaveText(
            'Are you sure you want to delete "hodge.espinoza@cubix.io"?'
        )

        await page.locator('label', { hasText: 'I understand' }).click() // Acknowledge deletion
        await page.locator('.LemonButton--secondary', { hasText: 'Delete person' }).click()

        await expect(page.locator('.Toastify__toast-body')).toHaveText(
            'hodge.espinoza@cubix.io was removed from the project'
        )

        await expect(page.locator('tr', { hasText: 'hodge.espinoza@cubix.io' })).not.toBeVisible()
    })
})
