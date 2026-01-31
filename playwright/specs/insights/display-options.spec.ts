import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Display Options', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('toggle show values on series', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('check Show values on series', async () => {
            await page.getByText('Show values on series').click()
            await expect(page.getByRole('checkbox', { name: 'Show values on series' })).toBeChecked()
        })

        await test.step('uncheck Show values on series', async () => {
            await page.getByText('Show values on series').click()
            await expect(page.getByRole('checkbox', { name: 'Show values on series' })).not.toBeChecked()
        })
    })

    test('toggle show legend', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add breakdown by Browser', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('uncheck Show legend and verify', async () => {
            await page.getByText('Show legend').click()
            await expect(page.getByRole('checkbox', { name: 'Show legend' })).not.toBeChecked()
        })

        await test.step('re-check Show legend and verify', async () => {
            await page.getByText('Show legend').click()
            await expect(page.getByRole('checkbox', { name: 'Show legend' })).toBeChecked()
        })
    })

    test('enable show trend lines', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('check Show trend lines', async () => {
            await page.getByText('Show trend lines').click()
            await expect(page.getByRole('checkbox', { name: 'Show trend lines' })).toBeChecked()
        })
    })

    test('change y-axis scale to logarithmic', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('select Logarithmic for Y-axis scale', async () => {
            await page.getByRole('button', { name: 'Logarithmic' }).click()
        })

        await test.step('change back to Linear', async () => {
            await page.getByRole('button', { name: 'Linear' }).click()
        })
    })

    test('set y-axis unit', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('open Y-axis unit dropdown and select Duration (s)', async () => {
            await page.getByRole('button', { name: 'None' }).click()
            await page.getByRole('button', { name: 'Duration (s)' }).click()
        })
    })

    test('enable confidence intervals', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('toggle Show confidence intervals on', async () => {
            const toggle = page.getByRole('switch', { name: 'Show confidence intervals' })
            await toggle.scrollIntoViewIfNeeded()
            await toggle.click()
            await expect(toggle.locator('..')).toHaveClass(/LemonSwitch--checked/)
        })
    })

    test('enable moving average', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('toggle Show moving average on', async () => {
            const toggle = page.getByRole('switch', { name: 'Show moving average' })
            await toggle.scrollIntoViewIfNeeded()
            await toggle.click()
            await expect(toggle.locator('..')).toHaveClass(/LemonSwitch--checked/)
        })
    })

    test('change color customization', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('add breakdown by Browser', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
        })

        await test.step('open Options panel', async () => {
            await page.locator('[data-attr="insight-filters"]').getByRole('button', { name: 'Options' }).click()
        })

        await test.step('change color customization to By rank', async () => {
            await page.getByRole('button', { name: 'By rank' }).click()
        })
    })
})
