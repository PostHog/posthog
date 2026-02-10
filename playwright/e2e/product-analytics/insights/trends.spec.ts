import { InsightPage } from '../../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

test.describe('Trends insights', () => {
    test.setTimeout(60_000) // Many parallel tests doing /query calls ist just slow, we need to allow more time.

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Create and save a new insight', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to insights list', async () => {
            await insight.goToList()
            await expect(page.locator('table')).toBeVisible()
        })

        await test.step('create new Trends insight and verify defaults', async () => {
            await page.getByTestId('saved-insights-new-insight-button').click()
            await expect(insight.activeTab).toContainText('Trends')
            await insight.trends.waitForChart()
            await expect(insight.trends.firstSeries).toHaveText('Pageview')
            await expect(page.getByText('Total count')).toBeVisible()
            await expect(page.getByText('Last 7 days')).toBeVisible()
            await expect(page.getByText('Line chart')).toBeVisible()
            await expect(page.getByText('No comparison')).toBeVisible()
        })

        await test.step('set name and description, then save', async () => {
            await insight.editName('User Signups')
            const descriptionField = page.getByTestId('scene-description-textarea')
            await descriptionField.click()
            await descriptionField.fill('Tracking daily user signups')
            await descriptionField.blur()
            await insight.save()
            await expect(insight.editButton).toBeVisible()
            expect(page.url()).not.toContain('/new')
        })
    })

    test('Add, duplicate, and delete series', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('change event on first series', async () => {
            await insight.trends.selectEvent(0, 'downloaded_file')
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
        })

        await test.step('add second series and verify both appear', async () => {
            await insight.trends.addSeries()
            await insight.trends.selectEvent(1, 'Pageleave')
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
            await expect(insight.trends.detailsLabels).toHaveCount(2)
        })

        await test.step('add second series via Actions tab', async () => {
            await insight.trends.addSeries()
            await insight.trends.seriesEventButton(2).click()
            await insight.trends.selectTaxonomicTab('actions')
            await insight.trends.taxonomicResults().first().click()
            await insight.trends.waitForChart()
        })

        await test.step('duplicate first series', async () => {
            await insight.trends.duplicateSeries(0)
            await expect(page.getByTestId('trend-element-subject-3')).toBeVisible()
        })

        await test.step('delete first series', async () => {
            await insight.trends.deleteSeries(0)
        })
    })

    test('Switch between aggregation methods', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('change to Unique users', async () => {
            await insight.trends.mathSelector(0).click()
            const uniqueUsersOption = page.getByRole('menuitem', { name: 'Unique users' })
            await uniqueUsersOption.waitFor({ state: 'visible' })
            await uniqueUsersOption.click()
            await insight.trends.waitForChart()
            await expect(page.getByText('Unique users').first()).toBeVisible()
        })

        await test.step('change to Count per user with median', async () => {
            await insight.trends.mathSelector(0).click()
            const countPerUserItem = page.getByRole('menuitem', { name: /event count per user/ })
            await countPerUserItem.waitFor({ state: 'visible' })
            await countPerUserItem.getByRole('button').click()
            await page.getByRole('menuitem', { name: 'median' }).click()
            await insight.trends.waitForChart()
            await page.keyboard.press('Escape')
        })

        await test.step('change to Property value with sum', async () => {
            await insight.trends.mathSelector(0).click()
            const propertyValueItem = page.getByRole('menuitem', { name: /property value/ })
            await propertyValueItem.waitFor({ state: 'visible' })
            await propertyValueItem.getByRole('button').click()
            await page.getByRole('menuitem', { name: 'sum' }).click()
            await insight.trends.waitForChart()
            await page.keyboard.press('Escape')
        })

        await test.step('change to Weekly then Monthly active users', async () => {
            await insight.trends.mathSelector(0).click()
            const weeklyOption = page.getByRole('menuitem', { name: /Weekly active users/ })
            await weeklyOption.waitFor({ state: 'visible' })
            await weeklyOption.click()
            await insight.trends.waitForChart()

            await insight.trends.mathSelector(0).click()
            await page.getByRole('menuitem', { name: /Monthly active users/ }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Switch between chart types', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        const chartTypes = [
            { name: /^Bar chart Trends over time/, label: 'Bar chart' },
            { name: /^Number/, label: 'Number' },
            { name: /^Area chart/, label: 'Area chart' },
            { name: /^Stacked bar chart/, label: 'Stacked bar chart' },
            { name: /^Line chart \(cumulative\)/, label: 'Line chart (cumulative)' },
            { name: /^Table/, label: 'Table' },
        ]

        for (const chartType of chartTypes) {
            await test.step(`select ${chartType.label}`, async () => {
                await insight.trends.selectChartType(chartType.name)
                await expect(insight.trends.chartTypeButton).toContainText(chartType.label)
            })
        }

        await test.step('select Pie chart with breakdown', async () => {
            await insight.trends.selectChartType(/^Line chart Trends/)
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
            await insight.trends.selectChartType(/^Pie chart/)
            await expect(insight.trends.chartTypeButton).toContainText('Pie chart')
        })

        await test.step('select World map with country breakdown', async () => {
            await insight.trends.selectChartType(/^Line chart Trends/)
            await insight.trends.addBreakdown('Country code')
            await insight.trends.waitForChart()
            await insight.trends.chartTypeButton.click()
            const worldMapItem = page.getByRole('menuitem', { name: /Visualize data by country/ })
            await worldMapItem.scrollIntoViewIfNeeded()
            await worldMapItem.click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chartTypeButton).toContainText('World map')
        })
    })

    test('Change date ranges, intervals, and comparison', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('select Last 30 days', async () => {
            await insight.trends.selectDateRange('Last 30 days')
            await expect(insight.trends.dateRangeButton).toContainText('Last 30 days')
        })

        await test.step('use custom fixed date range', async () => {
            await insight.trends.dateRangeButton.click()
            await page.getByText('Custom fixed date range').click()
            // In LemonCalendarRange, click start date then end date directly (no Start:/End: buttons)
            await page.locator('.LemonCalendar').getByRole('button', { name: '1', exact: true }).first().click()
            await page.locator('.LemonCalendar').getByRole('button', { name: '15', exact: true }).first().click()
            await page.getByRole('button', { name: 'Apply' }).click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })

        await test.step('select All time', async () => {
            await insight.trends.selectDateRange('All time')
            await expect(insight.trends.dateRangeButton).toContainText('All time')
        })

        await test.step('use rolling date range with custom value', async () => {
            await insight.trends.dateRangeButton.click()
            const numberInput = page.locator('input[type="number"]').first()
            await numberInput.fill('14')
            await numberInput.press('Enter')
            await insight.trends.waitForChart()
            await expect(insight.trends.dateRangeButton).toContainText('14')
        })

        await test.step('change interval to week with Last 90 days', async () => {
            await insight.trends.selectDateRange('Last 90 days')
            await insight.trends.selectInterval('week')
        })

        await test.step('change to hourly interval with Last 24 hours', async () => {
            await insight.trends.selectDateRange('Last 24 hours')
            await insight.trends.unpinInterval()
            await insight.trends.selectInterval('hour')
            await expect(insight.trends.chart).toBeVisible()
        })

        await test.step('enable comparison to previous period', async () => {
            await insight.trends.selectDateRange('Last 7 days')
            await expect(insight.trends.comparisonButton).toContainText('No comparison')
            await insight.trends.selectComparison('Compare to previous period')
            await expect(insight.trends.comparisonButton).toContainText('Previous period')
        })

        await test.step('disable comparison', async () => {
            await insight.trends.selectComparison('No comparison between periods')
            await expect(insight.trends.comparisonButton).toContainText('No comparison')
        })
    })

    test('Add and remove breakdowns', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('add breakdown by Browser', async () => {
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
            await insight.trends.waitForDetailsTable()
            const rowCount = await insight.trends.detailsLabels.count()
            expect(rowCount).toBeGreaterThanOrEqual(1)
        })

        await test.step('add second breakdown by OS', async () => {
            await insight.trends.addBreakdown('OS')
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })

        await test.step('remove a breakdown', async () => {
            await insight.trends.removeBreakdown()
            await expect(insight.trends.chart).toBeVisible()
        })

        await test.step('add breakdown by Person property', async () => {
            await insight.trends.removeBreakdown()
            await insight.trends.breakdownButton.click()
            await insight.trends.selectTaxonomicTab('person_properties')
            await insight.trends.taxonomicResults().first().click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Add filter groups and toggle internal users filter', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('add a global filter group with Browser property', async () => {
            await page.getByRole('button', { name: 'Add filter group' }).click()
            await page.getByRole('button', { name: 'Filter', exact: true }).click()
            const searchField = page.getByTestId('taxonomic-filter-searchfield')
            await searchField.waitFor({ state: 'visible' })
            await searchField.fill('Browser')
            await insight.trends.taxonomicResults().first().click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })

        await test.step('toggle filter out internal and test users', async () => {
            const filterSwitch = page.getByRole('switch', { name: 'Filter out internal and test users' })
            await filterSwitch.click()
            await insight.trends.waitForChart()
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('Enable and disable formula mode', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.addSeries()
        await expect(insight.trends.secondSeries).toBeVisible()

        await test.step('enable formula and enter expression', async () => {
            await insight.trends.setFormula('A + B')
            await expect(insight.trends.formulaInput.first()).toHaveValue('A + B')
            await insight.trends.waitForChart()
            await expect(insight.trends.detailsTable).toBeVisible()
        })

        await test.step('disable formula mode', async () => {
            await insight.trends.formulaSwitch.click()
            await expect(insight.trends.formulaInput).not.toBeVisible()
            await expect(insight.trends.firstSeries).toBeVisible()
            await expect(insight.trends.secondSeries).toBeVisible()
        })
    })

    test('Configure display options and goal lines', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()

        await test.step('toggle show values on series', async () => {
            await insight.trends.openOptionsPanel()
            await page.getByText('Show values on series').click()
            await expect(page.getByRole('checkbox', { name: 'Show values on series' })).toBeChecked()
            await page.getByText('Show values on series').click()
            await expect(page.getByRole('checkbox', { name: 'Show values on series' })).not.toBeChecked()
        })

        await test.step('enable trend lines', async () => {
            await page.getByText('Show trend lines').click()
            await expect(page.getByRole('checkbox', { name: 'Show trend lines' })).toBeChecked()
        })

        await test.step('change y-axis scale to Logarithmic and back', async () => {
            await page.getByRole('button', { name: 'Logarithmic' }).click()
            await page.getByRole('button', { name: 'Linear' }).click()
        })

        await test.step('set y-axis unit to Duration', async () => {
            const unitPicker = page.getByTestId('chart-aggregation-axis-format')
            await unitPicker.click()
            await page.locator('.Popover__content').getByRole('button', { name: 'Duration (s)', exact: true }).click()
        })

        await test.step('enable confidence intervals and moving average', async () => {
            const unitPicker = page.getByTestId('chart-aggregation-axis-format')
            await unitPicker.waitFor({ state: 'visible' })
            await unitPicker.click()
            const unitPopover = page.locator('.Popover__content').filter({ hasText: 'None' })
            await unitPopover.waitFor({ state: 'visible' })
            await unitPopover.getByRole('button', { name: 'None', exact: true }).click()

            const ciToggle = page.getByRole('switch', { name: 'Show confidence intervals' })
            await expect(ciToggle).toBeEnabled({ timeout: 10000 })
            await ciToggle.click()
            await expect(ciToggle.locator('..')).toHaveClass(/LemonSwitch--checked/)

            const maToggle = page.getByRole('switch', { name: 'Show moving average' })
            await expect(maToggle).toBeVisible()
            await maToggle.click()
            await expect(maToggle.locator('..')).toHaveClass(/LemonSwitch--checked/)
        })

        await test.step('add a goal line with value and label', async () => {
            await page.getByText('Advanced options').click()
            await page.getByRole('button', { name: 'Add goal line' }).click()
            await page.locator('input[type="number"]').last().fill('100')
            await page.getByPlaceholder('Label').last().fill('Target')
            await expect(page.locator('input[type="number"]').last()).toHaveValue('100')
            await expect(page.getByPlaceholder('Label').last()).toHaveValue('Target')
        })

        await test.step('remove the goal line', async () => {
            await page.getByRole('button', { name: 'Delete goal line' }).click()
            await expect(page.locator('input[type="number"]')).toHaveCount(0)
        })
    })

    test('Edit saved insight and save as new', async ({ page }) => {
        test.setTimeout(45000)
        const insight = new InsightPage(page)

        await test.step('create and save insight', async () => {
            await insight.goToNewTrends()
            await insight.editName('Download Activity')
            await expect(insight.topBarName).toContainText('Download Activity', { timeout: 10000 })
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('save as new insight', async () => {
            await insight.edit()
            await insight.saveAsNew('Copied Activity')
            await expect(insight.topBarName).toContainText('Copied Activity', { timeout: 10000 })
        })
    })

    test('Export as CSV and XLSX', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()
        await insight.trends.waitForDetailsTable()

        await test.step('exports as CSV', async () => {
            await page.getByTestId('export-button').click()
            const csvDownload = page.waitForEvent('download')
            await page.getByTestId('export-button-csv').click()
            const download = await csvDownload
            expect(download.suggestedFilename()).toMatch(/\.csv$/i)
        })

        await test.step('export as XLSX', async () => {
            await page.getByTestId('export-button').click()
            const xlsxDownload = page.waitForEvent('download')
            await page.getByTestId('export-button-xlsx').click()
            const download = await xlsxDownload
            expect(download.suggestedFilename()).toMatch(/\.xlsx$/i)
        })
    })
})
