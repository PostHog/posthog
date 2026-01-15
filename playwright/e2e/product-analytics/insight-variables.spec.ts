import { expect, test } from '../../utils/playwright-test-base'

test.describe('insight variables', () => {
    test.skip('show correctly on dashboards', async ({ page }) => {
        // FIXME: This test requires the InsightVariablesDataGenerator to run during setup
        // which creates the "Insight variables" dashboard with specific test data.
        // Currently, the default demo data doesn't include this dashboard.
        // To fix: Either add InsightVariablesDataGenerator to the default demo data,
        // or create a custom setup function that generates this data before the test runs.
        
        // Go to "Insight variables" dashboard.
        await page.goToMenuItem('dashboards')
        await page.getByText('Insight variables').click()

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
