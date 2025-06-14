import { Page } from '@playwright/test'

import { expect, test } from '../utils/playwright-test-base'

const createAction = async (page: Page, actionName: string): Promise<void> => {
    await page.locator('[data-attr=create-action]').first().click()
    await expect(page.locator('.LemonButton')).toContainText('From event or pageview')
    await page.locator('[data-attr=new-action-pageview]').click({ force: true })
    await expect(page.locator('input[name="item-name-large"]')).toBeVisible()

    await page.fill('input[name="item-name-large"]', actionName)
    await page.locator('[data-attr=action-type-pageview]').click() // Click "Pageview"
    await page.locator('[data-attr=edit-action-url-input]').click()
    await page.fill('[data-attr=edit-action-url-input]', process.env.BASE_URL || '')

    await page.locator('[data-attr=save-action-button]').first().click()

    await expect(page.locator('text=Action saved')).toBeVisible()
}

test.describe('Action Events', () => {
    let actionName: string

    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('action')
        actionName = Math.floor(Math.random() * 1e6).toString()
    })

    test('Create action event', async ({ page }) => {
        await createAction(page, actionName)

        // Test the action is immediately available
        await page.click('[data-attr=nav-menu-insight]')
        await page.click('[data-attr="menu-item-insight"]')

        await page.click('text=Add graph series')
        await page.click('[data-attr=trend-element-subject-1]')
        await page.fill('[data-attr=taxonomic-filter-searchfield]', actionName)
        await page.click('[data-attr=taxonomic-tab-actions]')
        await page.click('[data-attr=prop-filter-actions-0]')
        await expect(page.locator('[data-attr=trend-element-subject-1] span')).toContainText(actionName)
    })

    test('Notifies when an action event with this name already exists', async ({ page }) => {
        await createAction(page, actionName)
        await page.goToMenuItem('action')
        await createAction(page, actionName)

        // Oh noes, there already is an action with this name
        await expect(page.locator('text=Action with this name already exists')).toBeVisible()

        // Let's see it
        await page.click('text=Edit it here')

        // We should now be seeing the action from "Create action"
        await expect(page.locator('[data-attr=edit-action-url-input]')).toHaveValue(process.env.BASE_URL || '')
    })

    test('Click on an action', async ({ page }) => {
        await expect(page.locator('[data-attr=actions-table]')).toBeVisible()
        await page.click('[data-attr=action-link-0]')
        await expect(page.locator('[data-attr=edit-prop-item-name-large]')).toBeVisible()
    })
})
