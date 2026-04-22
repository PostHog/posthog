import { expect } from '@playwright/test'

import { test } from '../utils/playwright-test-base'

test.describe('Scene tabs', () => {
    test('closing a tab preserves remaining tab widths until mouse leaves', async ({ page }) => {
        // Navigate to a few different pages to open multiple tabs
        await page.goto('/project/1/activity/explore')
        await page.waitForSelector('.scene-tab-row')

        // Open new tabs by clicking the new tab button multiple times
        for (let i = 0; i < 3; i++) {
            await page.click('[data-attr="scene-tab-new-button"]')
            await page.waitForTimeout(300)
        }

        // Navigate each new tab to a different page so they have distinct titles
        const tabs = page.locator('.scene-tab-row [data-tab-id]')
        const tabCount = await tabs.count()

        // Verify we have multiple tabs
        expect(tabCount).toBeGreaterThanOrEqual(4)

        // Screenshot: tabs before closing
        const tabRow = page.locator('.scene-tab-row')
        await expect(tabRow).toHaveScreenshot('tabs-before-close.png')

        // Record the widths of all tabs before closing
        const widthsBefore = await tabs.evaluateAll((els) =>
            els.map((el) => ({ id: el.getAttribute('data-tab-id'), width: el.getBoundingClientRect().width }))
        )

        // Find a non-active, closable tab (not the first or last)
        // We'll close the second-to-last tab
        const tabToCloseIndex = tabCount - 2
        const tabToClose = tabs.nth(tabToCloseIndex)
        const tabToCloseId = await tabToClose.getAttribute('data-tab-id')

        // Hover over the tab to reveal close button, then click it
        await tabToClose.hover()
        const closeButton = tabToClose.locator('button').first()
        await closeButton.click()

        // Small wait for the frozen widths to take effect
        await page.waitForTimeout(100)

        // Screenshot: tabs immediately after closing (widths should be frozen)
        await expect(tabRow).toHaveScreenshot('tabs-after-close-frozen.png')

        // Verify the remaining tabs have frozen widths matching their pre-close sizes
        const remainingTabs = page.locator('.scene-tab-row [data-tab-id]')
        const widthsAfterClose = await remainingTabs.evaluateAll((els) =>
            els.map((el) => ({ id: el.getAttribute('data-tab-id'), width: el.getBoundingClientRect().width }))
        )

        // All remaining tabs should have their width frozen to what it was before
        for (const afterTab of widthsAfterClose) {
            const beforeTab = widthsBefore.find((b) => b.id === afterTab.id)
            if (beforeTab && afterTab.id !== tabToCloseId) {
                expect(Math.abs(afterTab.width - beforeTab.width)).toBeLessThan(2)
            }
        }

        // Move the mouse out of the tab row to unfreeze widths
        await page.mouse.move(0, 400)
        await page.waitForTimeout(100)

        // Screenshot: tabs after mouse leaves (widths should be natural/recalculated)
        await expect(tabRow).toHaveScreenshot('tabs-after-mouse-leave.png')
    })
})
