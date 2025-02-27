import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Notebooks creation and deletion', () => {
    async function visitNotebooksList(page): Promise<void> {
        await page.goToMenuItem('notebooks')
        await expect(page.locator('h1')).toContainText('Notebooks')
    }

    async function createNotebookAndFindInList(page, notebookTitle: string): Promise<void> {
        await page.locator('[data-attr="new-notebook"]').click()
        await expect(page.locator('.NotebookEditor')).toBeVisible()
        await page.keyboard.type(notebookTitle)
        // go back to list
        await visitNotebooksList(page)
        await page.locator('[data-attr="notebooks-search"]').fill(notebookTitle)
    }

    test.beforeEach(async ({ page }) => {
        await visitNotebooksList(page)
    })

    test('can create and name a notebook', async ({ page }) => {
        const notebookTitle = randomString('My new notebook')
        await createNotebookAndFindInList(page, notebookTitle)
        await expect(page.locator('[data-attr="notebooks-table"] tbody tr')).toHaveCount(1)
    })

    test('can delete a notebook', async ({ page }) => {
        const notebookTitle = randomString('My notebook to delete')
        await createNotebookAndFindInList(page, notebookTitle)

        await page
            .locator('[data-attr="notebooks-table"]')
            .locator('tr', { hasText: notebookTitle })
            .locator('[aria-label="more"]')
            .click()
        await page.locator('.LemonButton', { hasText: 'Delete' }).click()

        await expect(page.locator('[data-attr="notebooks-table"]')).not.toContainText(notebookTitle)
    })
})
