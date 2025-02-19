import { expect, test } from '../utils/playwright-test-base'

test.describe('Event Definitions', () => {
    test('See recordings action', async ({ page }) => {
        await page.goToMenuItem('datamanagement')

        // default tab is events
        await expect(page.locator('[data-attr="data-management-events-tab"]')).toBeVisible()
        await page.waitForSelector('tbody tr:has-text("Loading… Loading… Loading…")', { state: 'detached' })

        await expect(page.locator('tbody tr .LemonButton').first()).toBeVisible()
        await expect(page.locator('[data-attr=events-definition-table]')).toBeVisible()
        await page.locator('button[aria-label="more"]').first().click()

        const eventName = await page.locator('tbody tr .PropertyKeyInfo__text').first().innerText()

        await expect(page.locator('[data-attr=event-definitions-table-view-recordings]')).toBeVisible()
        await page.locator('[data-attr=event-definitions-table-view-recordings]').click()
        expect(page.url()).toMatch(/replay/)

        await expect(page.locator('.UniversalFilterButton').first()).toContainText(eventName, { ignoreCase: true })
    })
})
