import { Locator, Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'

function datasetsTab(page: Page): Locator {
    return page.locator('[data-attr="datasets-tab"]')
}

test.describe('LLM Analytics: Datasets', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('llm-analytics')
        await datasetsTab(page).click()
    })

    test('Resets the create dataset form when leaving the page', async ({ page }) => {
        // Open the form
        await expect(page.getByTestId('create-dataset-form')).toBeVisible()
        await page.getByTestId('create-dataset-form').click()

        // Fill the form
        await expect(page.getByTestId('edit-dataset-name-input')).toBeVisible()
        await expect(page.getByTestId('edit-dataset-name-input')).toHaveValue('')
        await page.getByTestId('edit-dataset-name-input').fill('Test Dataset')
        await expect(page.getByTestId('edit-dataset-name-input')).toHaveValue('Test Dataset')
        await page.getByTestId('edit-dataset-description-input').fill('Test Description')
        await expect(page.getByTestId('edit-dataset-description-input')).toHaveValue('Test Description')

        // Go back to the datasets page
        await page.goBack()
        await expect(datasetsTab(page)).toBeVisible()

        // Open the form
        await datasetsTab(page).click()

        // Check that the form is empty
        await expect(page.getByTestId('edit-dataset-name-input')).toBeVisible()
        await expect(page.getByTestId('edit-dataset-name-input')).toHaveValue('')
        await expect(page.getByTestId('edit-dataset-description-input')).toHaveValue('')
        await expect(page.getByTestId('edit-dataset-metadata-input')).toHaveValue('')
    })
})
