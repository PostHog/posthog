import { expect, test } from '../../utils/playwright-test-base'

test.describe('insight variables', () => {
    // :FIXME: This test is flaky on CI.
    test.skip('show correctly on dashboards', async ({ page }) => {
        // Go to "Insight variables" dashboard.
        await page.goToMenuItem('dashboards')
        await page.getByText('Insight variables').click()

        // Add a temporary override
        await page.goto(page.url() + '?query_variables=%7B"variable_4"%3A40%7D%20')

        const cardForDefaultVariable = page
            .getByText('Variable default')
            .locator('xpath=ancestor::*[contains(@class, "InsightCard")]')
        await expect(cardForDefaultVariable.locator('.BoldNumber')).toHaveText('10')

        // :FIXME: This override gets cancelled out when setting a temporary override.
        // const cardForDashboardOverride = page
        //     .getByText('Dashboard override')
        //     .locator('xpath=ancestor::*[contains(@class, "InsightCard")]')
        // await cardForDashboardOverride.highlight()
        // await expect(cardForDashboardOverride.locator('.BoldNumber')).toHaveText('20')

        const cardForInsightOverride = page
            .getByText('Insight override')
            .locator('xpath=ancestor::*[contains(@class, "InsightCard")]')
        await expect(cardForInsightOverride.locator('.BoldNumber')).toHaveText('30')

        const cardForURLOverride = page
            .getByText('Temporary override')
            .locator('xpath=ancestor::*[contains(@class, "InsightCard")]')
        await expect(cardForURLOverride.locator('.BoldNumber')).toHaveText('40')
    })
})
