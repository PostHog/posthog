import { randomString } from '../../utils'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('Insights - saved', () => {
    test('If cache empty, initiate async refresh', async ({ page }) => {
        // create an insight
        const newInsightName = randomString('saved insight')
        await page.goto('/saved_insights')
        await page.locator('[data-attr=saved-insights-new-insight-dropdown]').click()
        await page.locator('[data-attr-insight-type="TRENDS"]').click()
        await page.locator('[data-attr="top-bar-name"] button').click()
        await page.locator('[data-attr="top-bar-name"] input').fill(newInsightName)
        await page.locator('[data-attr="top-bar-name"] button[title="Save"]').click()
        await page.locator('[data-attr="insight-save-button"]').click()
        const shortId = await page.url().then((url) => url.split('/').pop())

        // reset the "insight cache" if you have that, e.g. request or route
        // ...
        // open the insight
        await page.goto(`/insights/${shortId}`)
        // check that it triggers refresh=async
        // ...
        await expect(page.locator('[data-attr="trend-line-graph"]')).toBeVisible()
    })
})
