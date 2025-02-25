import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Insights', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/insights/new')
    })

    test('Saving an insight sets breadcrumbs', async ({ page }) => {
        const name = randomString('insight name')
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(name)
        await page.locator('[data-attr="top-bar-name"] [title="Save"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()
        await expect(page).not.toHaveURL(/new/)

        await expect(page.locator('[data-attr=breadcrumb-Dashboards]')).toHaveText('Product analytics')
        await expect(page.locator('[data-attr^="breadcrumb-Insight:"]')).toHaveText(name)
    })

    test('Can change insight name, undo', async ({ page }) => {
        // create
        const startingName = randomString('start-')
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(startingName)
        await page.locator('[data-attr="top-bar-name"] [title="Save"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()

        // edit name
        const editedName = randomString('edited-')
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(editedName)
        await page.locator('[data-attr="top-bar-name"] [title="Save"]').click()

        await page.locator('[data-attr="edit-insight-undo"]').click()
        await expect(page.locator('[data-attr="top-bar-name"]')).not.toContainText(editedName)
        await expect(page.locator('[data-attr="top-bar-name"]')).toContainText(startingName)
    })

    test('Stickiness graph', async ({ page }) => {
        await page.locator('role=tab', { name: 'Stickiness' }).click()
        await page.click('[data-attr=add-action-event-button]')
        await expect(page.locator('[data-attr=trend-element-subject-1]')).toBeVisible()
        await expect(page.locator('[data-attr=trend-line-graph]')).toBeVisible()
        // can't do breakdown
        await expect(page.locator('[data-attr=add-breakdown-button]')).toHaveCount(0)
    })

    test('Lifecycle graph', async ({ page }) => {
        await expect(page.locator('[data-attr=trend-line-graph]')).toBeVisible()
        await page.locator('role=tab', { name: 'Lifecycle' }).click()
        await expect(page.locator('text=Lifecycle Toggles')).toBeVisible()
        await expect(page.locator('[data-attr=trend-line-graph]')).toBeVisible()
        await expect(page.locator('[data-attr=add-breakdown-button]')).toHaveCount(0)
        await expect(page.locator('[data-attr=add-action-event-button]')).toHaveCount(0)
    })

    test('Loads default filters correctly', async ({ page }) => {
        // in cypress we tested that it had "Pageview" by default
        await expect(page.locator('[data-attr=trend-element-subject-0]')).toContainText('Pageview')
        await expect(page.locator('[data-attr=trend-line-graph]')).toBeVisible()
        // add new series
        await page.click('text=Add graph series')
        await expect(page.locator('[data-attr=trend-element-subject-1]')).toBeVisible()
    })

    test('Cannot see tags or description if not on paid tier', async ({ page }) => {
        await expect(page.locator('.insight-description')).toHaveCount(0)
        await expect(page.locator('[data-attr=insight-tags]')).toHaveCount(0)
    })
})
