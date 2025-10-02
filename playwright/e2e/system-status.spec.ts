import { expect, test } from '../utils/playwright-test-base'

test.describe('System Status', () => {
    test('System Status loaded', async ({ page }) => {
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-instance-panel]').click()
        await expect(page.locator('table')).toHaveText(/Events in ClickHouse/)
    })

    test('System Status visual regression with timestamp', async ({ page }) => {
        await page.locator('[data-attr=menu-item-me]').click()
        await page.locator('[data-attr=top-menu-instance-panel]').click()
        await expect(page.locator('table')).toHaveText(/Events in ClickHouse/)

        // Add a timestamp to the page that will change every run, causing flapping
        await page.evaluate(() => {
            const timestampDiv = document.createElement('div')
            timestampDiv.id = 'flap-test-timestamp'
            timestampDiv.style.cssText =
                'position: fixed; top: 10px; right: 10px; background: yellow; padding: 10px; z-index: 9999; font-size: 14px;'
            timestampDiv.textContent = `Test run: ${new Date().toISOString()}`
            document.body.appendChild(timestampDiv)
        })

        await page.screenshot({
            path: '__snapshots__/system-status-flap-test.png',
            fullPage: true,
        })
    })
})
