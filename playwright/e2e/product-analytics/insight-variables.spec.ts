import { expect, test } from '../../utils/playwright-test-base'

test.describe('insight variables', () => {
    test('show correctly on dashboards', async ({ page }) => {
        // Go to "Insight variables" dashboard.
        await page.goToMenuItem('dashboards')
        
        // Wait for the dashboard list to load and click on "Insight variables"
        const insightVariablesDashboard = page.getByText('Insight variables')
        await expect(insightVariablesDashboard).toBeVisible()
        await insightVariablesDashboard.click()
        
        // Wait for the dashboard to load
        await expect(page.locator('.InsightCard').first()).toBeVisible()

        // Add a temporary override
        await page.goto(page.url() + '?query_variables=%7B"variable_4"%3A40%7D%20')

        const cardForDefaultVariable = page.locator('.InsightCard').nth(0)
        await cardForDefaultVariable.scrollIntoViewIfNeeded()
        await expect(cardForDefaultVariable.locator('.BoldNumber')).toHaveText('10')

        const cardForDashboardOverride = page.locator('.InsightCard').nth(1)
        await cardForDashboardOverride.scrollIntoViewIfNeeded()
        await expect(cardForDashboardOverride.locator('.BoldNumber')).toHaveText('20')

        const cardForInsightOverride = page.locator('.InsightCard').nth(2)
        await cardForInsightOverride.scrollIntoViewIfNeeded()
        await expect(cardForInsightOverride.locator('.BoldNumber')).toHaveText('30')

        const cardForURLOverride = page.locator('.InsightCard').nth(3)
        await cardForURLOverride.scrollIntoViewIfNeeded()
        await expect(cardForURLOverride.locator('.BoldNumber')).toHaveText('40')
    })
})
