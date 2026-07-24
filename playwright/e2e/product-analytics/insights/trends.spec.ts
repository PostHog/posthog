import { InsightPage } from '../../../page-models/insightPage'
import { customEventsWithBreakdown, pageviews } from '../../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const events = [...pageviews.events, ...customEventsWithBreakdown.events]

test.describe('Trends insights', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            no_demo_data: true,
            events,
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('View default pageview trends and verify daily totals', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('verify defaults are Pageview, Total count, Last 7 days', async () => {
            await expect(insight.trends.firstSeries).toHaveText('Pageview')
            await expect(page.getByText('Total count')).toBeVisible()
            await expect(page.getByText('Last 7 days')).toBeVisible()
        })

        await test.step('verify total pageview count in details table', async () => {
            await insight.trends.expectTotals([pageviews.expected.total])
        })
    })

    test('Add, duplicate, and delete series', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('change event to custom event and verify total', async () => {
            await insight.trends.selectEvent(0, customEventsWithBreakdown.eventName)
            await insight.trends.waitForChart()
            await insight.trends.expectTotals([customEventsWithBreakdown.expected.total])
        })

        await test.step('add second series with pageview and verify both totals', async () => {
            await insight.trends.addSeries()
            await insight.trends.selectEvent(1, 'Pageview')
            await insight.trends.waitForChart()
            await insight.trends.expectTotals([customEventsWithBreakdown.expected.total, pageviews.expected.total])
        })

        await test.step('duplicate first series', async () => {
            await insight.trends.duplicateSeries(0)
            await expect(page.getByTestId('trend-element-subject-2')).toBeVisible()
        })

        await test.step('delete first series and verify count drops to two', async () => {
            await insight.trends.deleteSeries(0)
            await expect(page.getByTestId('trend-element-subject-2')).not.toBeVisible()
            await expect(page.getByTestId('trend-element-subject-1')).toBeVisible()
        })
    })

    test('Switch aggregation to verify unique users and property value sums', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('switch to custom event', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.selectEvent(0, customEventsWithBreakdown.eventName)
            await insight.trends.waitForChart()
        })

        await test.step('set property value sum of amount and verify total = 35', async () => {
            await insight.trends.selectMathWithAggregation(0, /property value/, 'sum')
            await insight.trends.selectMathProperty('amount')
            await insight.trends.selectChartType(/^Number/)
            await expect(insight.trends.boldNumber).toContainText(customEventsWithBreakdown.expected.amountSum)
        })

        await test.step('switch to unique users and verify bold number = 5', async () => {
            await insight.trends.selectMath(0, 'Unique users')
            await expect(insight.trends.boldNumber).toContainText(customEventsWithBreakdown.expected.uniqueUsers)
        })

        await test.step('switch to total count and verify bold number = 8', async () => {
            await insight.trends.selectMath(0, 'Total count')
            await expect(insight.trends.boldNumber).toContainText(customEventsWithBreakdown.expected.total)
        })
    })

    test('View data as Number chart, cumulative line, and table', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('cumulative line chart shows total in details table', async () => {
            await insight.trends.selectChartType(/^Line chart \(cumulative\)/)
            await insight.trends.expectTotals([pageviews.expected.total])
        })

        await test.step('Number chart shows bold number = 38', async () => {
            await insight.trends.selectChartType(/^Number/)
            await expect(insight.trends.boldNumber).toBeVisible()
            await expect(insight.trends.boldNumber).toContainText(pageviews.expected.total)
        })

        await test.step('enable comparison and verify no NaN', async () => {
            await insight.trends.selectComparison('Compare to previous period')
            await expect(insight.trends.boldNumberComparison).toBeVisible()
            const comparisonText = await insight.trends.boldNumberComparison.textContent()
            expect(comparisonText).not.toContain('NaN')
            expect(comparisonText).not.toContain('undefined')
        })
    })

    test('Filter by date range and verify totals change', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('Last 7 days shows total = 38', async () => {
            await insight.trends.expectTotals([pageviews.expected.total])
        })

        await test.step('Last 24 hours shows total = 2', async () => {
            await insight.trends.selectDateRange('Last 24 hours')
            await insight.trends.expectTotals(['2'])
        })

        await test.step('enable comparison and verify no NaN', async () => {
            await insight.trends.selectComparison('Compare to previous period')
            await expect(insight.trends.comparisonButton).toContainText('Previous period')
            await insight.trends.waitForDetailsTable()
            const tableText = await insight.trends.detailsTable.textContent()
            expect(tableText).not.toContain('NaN')
        })

        await test.step('disable comparison', async () => {
            await insight.trends.selectComparison('No comparison between periods')
            await expect(insight.trends.comparisonButton).toContainText('No comparison')
        })
    })

    test('Break down custom events by browser and verify per-browser totals', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('add Browser breakdown and switch to custom event', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
            await insight.trends.selectEvent(0, customEventsWithBreakdown.eventName)
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
        })

        await test.step('verify Chrome = 5 and Firefox = 3', async () => {
            await insight.trends.expectRowTotal('Chrome', customEventsWithBreakdown.expected.chromeCount)
            await insight.trends.expectRowTotal('Firefox', customEventsWithBreakdown.expected.firefoxCount)
        })

        await test.step('remove breakdown and verify single total returns', async () => {
            await insight.trends.removeBreakdown()
            await insight.trends.waitForChart()
            await insight.trends.expectTotals([customEventsWithBreakdown.expected.total])
        })
    })

    test('Combine two series with a formula and verify computed total', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('add pageview and custom event as two series', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addSeries()
            await insight.trends.selectEvent(1, customEventsWithBreakdown.eventName)
            await insight.trends.waitForChart()
        })

        await test.step('enable formula A + B and verify computed total', async () => {
            await insight.trends.setFormula('A + B')
            await insight.trends.waitForChart()
            await insight.trends.expectTotals(['46'])
        })

        await test.step('disable formula mode and verify both series return', async () => {
            await insight.trends.formulaSwitch.click()
            await expect(insight.trends.formulaInput).not.toBeVisible()
            await expect(insight.trends.firstSeries).toBeVisible()
            await expect(insight.trends.secondSeries).toBeVisible()
        })
    })

    test('Display negative values and formatted numbers correctly in details table', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('set up custom event with browser breakdown and property sum', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
            await insight.trends.selectEvent(0, customEventsWithBreakdown.eventName)
            await insight.trends.waitForChart()
            await insight.trends.selectMathWithAggregation(0, /property value/, 'sum')
            await insight.trends.selectMathProperty('amount')
            await insight.trends.waitForDetailsTable()
        })

        await test.step('verify Chrome row totals 50 and Firefox row totals -15', async () => {
            const rows = insight.trends.detailsTable.locator('tbody tr')
            const chromeRow = rows.filter({ hasText: 'Chrome' })
            const firefoxRow = rows.filter({ hasText: 'Firefox' })
            await expect(chromeRow).toContainText(customEventsWithBreakdown.expected.chromeAmountSum)
            await expect(firefoxRow).toContainText(customEventsWithBreakdown.expected.firefoxAmountSum)
        })

        await test.step('switch to Number chart and verify bold number shows net sum of 35', async () => {
            await insight.trends.selectChartType(/^Number/)
            await expect(insight.trends.boldNumber).toContainText(customEventsWithBreakdown.expected.amountSum)
        })

        await test.step('switch to line chart and set axis format to Percentage to verify % in details', async () => {
            await insight.trends.selectChartType(/^Line chart(?! \()/)
            await insight.trends.waitForDetailsTable()
            await insight.trends.openOptionsPanel()
            const formatPicker = page.getByTestId('chart-aggregation-axis-format')
            await formatPicker.waitFor({ state: 'visible' })
            await formatPicker.click()
            await page.getByRole('button', { name: 'Percent (0-100)' }).click()
            await page.keyboard.press('Escape')
            await expect(insight.trends.detailsTable).toContainText('35%')
            await expect(insight.trends.detailsTable).toContainText('50%')
            await expect(insight.trends.detailsTable).toContainText('-15%')
        })

        await test.step('set axis format back to None and verify formatting is removed', async () => {
            await insight.trends.openOptionsPanel()
            const formatPicker = page.getByTestId('chart-aggregation-axis-format')
            await formatPicker.waitFor({ state: 'visible' })
            await formatPicker.click()
            await page.getByRole('button', { name: 'None' }).click()
            await page.keyboard.press('Escape')
            await expect(insight.trends.detailsTable).not.toContainText('35%')
        })
    })

    test('Hover chart to see tooltip with data point values', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create trends insight with pageviews', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('hover chart and verify tooltip appears with digits', async () => {
            await insight.trends.hoverChartAt(0.3, 0.5)
            const tooltipText = await insight.trends.tooltip.textContent()
            expect(tooltipText).not.toContain('NaN')
            expect(tooltipText).toMatch(/\d+/)
        })

        await test.step('move away and verify tooltip hides', async () => {
            await insight.trends.hoverAway()
            // The quill chart unmounts the tooltip on mouse-leave rather than fading a
            // persistent wrapper, so assert it detaches from the DOM.
            await expect(insight.trends.tooltip).toHaveCount(0, { timeout: 3000 })
        })

        await test.step('hover again and scroll to dismiss', async () => {
            await insight.trends.hoverChartAt(0.5, 0.5)
            await page.mouse.wheel(0, 200)
            await expect(insight.trends.tooltip).toHaveCount(0, { timeout: 3000 })
        })

        await test.step('add breakdown and verify tooltip shows Chrome and Firefox', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
            await insight.trends.selectEvent(0, customEventsWithBreakdown.eventName)
            await insight.trends.waitForChart()
            await insight.trends.hoverChartAt(0.5, 0.5)
            const multiText = await insight.trends.tooltip.textContent()
            expect(multiText).toContain('Chrome')
            expect(multiText).toContain('Firefox')
        })

        await test.step('navigate away and verify no orphaned tooltip', async () => {
            await insight.goToList()
            await expect(page.locator('table')).toBeVisible()
            await expect(insight.trends.tooltip).toHaveCount(0, { timeout: 3000 })
        })
    })
})
