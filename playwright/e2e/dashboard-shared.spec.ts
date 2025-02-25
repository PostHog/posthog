import { randomString } from '../utils'
import { expect, test } from '../utils/playwright-test-base'

test.describe('Shared dashboard', () => {
    test.beforeEach(async ({ page }) => {
        // intercept calls or do a "useSubscriptionStatus('unsubscribed')" equivalent
        // ...
        await page.goToMenuItem('dashboards')
    })

    test('Dashboard sharing can be enabled', async ({ page }) => {
        // create a dashboard from default template
        await page.locator('[data-attr="new-dashboard"]').click()
        await page.locator('[data-attr="create-dashboard-from-template"]').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(randomString('to be shared'))
        await page.locator('[data-attr="top-bar-name"] button:has-text("Save")').click()
        await expect(page.locator('.InsightCard')).toBeVisible()

        // open share modal
        await page.locator('[data-attr=dashboard-share-button]').click()
        await page.locator('[data-attr=sharing-switch]').click({ force: true })
        await expect(page.locator('text=Embed dashboard')).toBeVisible()

        await page.locator('[data-attr=copy-code-button]').click()
        // the user can read from clipboard and check the <iframe> text
        // ...
        await expect(page.locator('text=Copy public link')).toBeVisible()
        await page.locator('[data-attr=sharing-link-button]').click()
        // also check the public link is in the clipboard, etc.
    })

    test('Insights load for a shared dash if cache is empty', async ({ page }) => {
        // create a new dashboard, share it, then forcibly reset the "cache"
        // in cypress we used a custom task `cy.task('resetInsightCache')`
        // in playwright you might do your own route stubbing or clear the environment

        await page.locator('[data-attr="new-dashboard"]').click()
        await page.locator('[data-attr="create-dashboard-from-template"]').click()
        await page.locator('[data-attr="top-bar-name"] input').fill('Foobar 3001')
        await page.locator('[data-attr="top-bar-name"] button:has-text("Save")').click()
        await page.locator('[data-attr=dashboard-share-button]').click()
        await page.locator('[data-attr=sharing-switch]').click({ force: true })
        await page.locator('[data-attr=sharing-link-button]').click()
        const clipboardText = await page.evaluate(() => navigator.clipboard.readText())

        // reset your environment as needed
        // e.g. "resetInsightCache" again if implemented
        // then open the link in the same page or a new page
        await page.goto(clipboardText)
        // confirm the insights show up
        await expect(page.locator('.InsightCard')).toHaveCount(6)
        await expect(page.locator('[data-attr="insight-empty-state"]')).toHaveCount(0)
    })
})
