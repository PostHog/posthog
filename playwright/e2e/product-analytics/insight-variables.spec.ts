import { DashboardPage } from '../../page-models/dashboardPage'
import { expect, test } from '../../utils/playwright-test-base'

test.describe('insight variables', () => {
    test('show correctly on dashboards', async ({ page }) => {
        const dashboard = new DashboardPage(page)

        // Go to "Insight variables" dashboard.
        await page.goToMenuItem('dashboards')
        await page.getByText('Insight variables').click()

        // Add a temporary override
        await page.goto(page.url() + '?query_variables=%7B"variable_4"%3A40%7D%20')
        await expect(page.locator('.InsightCard').first()).toBeVisible()

        const cardForDefaultVariable = await dashboard.findCardByTitle('Variable default')
        await expect(cardForDefaultVariable.locator('.BoldNumber')).toHaveText('10')

        const cardForDashboardOverride = await dashboard.findCardByTitle('Dashboard override')
        await expect(cardForDashboardOverride.locator('.BoldNumber')).toHaveText('20')

        const cardForInsightOverride = await dashboard.findCardByTitle('Insight override')
        await expect(cardForInsightOverride.locator('.BoldNumber')).toHaveText('30')

        const cardForURLOverride = await dashboard.findCardByTitle('Temporary override')
        await expect(cardForURLOverride.locator('.BoldNumber')).toHaveText('40')
    })
})
