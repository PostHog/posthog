import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Surveys', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('surveys')
    })

    test('shows get started state on first load', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page.locator('text=Create your first survey')).toBeVisible()

        await page.click('[data-attr="create-survey"]')
        await page.click('[data-attr="new-blank-survey"]')
        await page.fill('[data-attr="survey-name"]', randomString('survey'))
        await page.click('[data-attr="save-survey"]')
        await expect(page.locator('[data-attr=success-toast]')).toContainText('created')

        await page.goToMenuItem('surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText('survey')
        await expect(page.locator('text=Create your first survey')).toHaveCount(0)
    })

    test('launch survey, stop survey, delete survey', async ({ page }) => {
        const name = randomString('My Survey')

        // create
        await page.click('[data-attr="new-survey"]')
        await page.click('[data-attr="new-blank-survey"]')
        await page.fill('[data-attr="survey-name"]', name)
        await page.click('[data-attr="save-survey"]')
        await expect(page.locator('button[data-attr="launch-survey"]')).toHaveText('Launch')

        // back to surveys
        await page.goToMenuItem('surveys')
        await expect(page.locator('[data-attr=surveys-table]')).toContainText(name)

        // open, launch
        await page.locator(`[data-row-key="${name}"]`).click()
        await page.locator('[data-attr="launch-survey"]').click()
        await expect(page.locator('.LemonModal__layout')).toContainText('Launch this survey?')
        await page.locator('.LemonModal__footer button', { hasText: 'Launch' }).click()

        // stop
        await page.locator('text=Stop').click()
        await expect(page.locator('.LemonModal__layout')).toContainText('Stop this survey?')
        await page.locator('.LemonModal__footer button', { hasText: 'Stop' }).click()

        // delete
        await page.locator('[data-attr="more-button"]').click()
        await page.locator('text=Delete').click()
        await expect(page.locator('.LemonModal__layout')).toContainText('Delete this survey?')
        await page.locator('.LemonModal__footer button', { hasText: 'Delete' }).click()
        await expect(page.locator('[data-attr=surveys-table] tbody')).toHaveCount(0)
    })
})
