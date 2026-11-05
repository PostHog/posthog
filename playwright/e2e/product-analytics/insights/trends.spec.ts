import { InsightPage } from '../../../page-models/insightPage'
import { randomString } from '../../../utils'
import { pageviews } from '../../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const events = pageviews.events

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

    // Changing the date range right after entering edit mode can race the editor's
    // hydration — a late insight load can revert the edit, leaving the save button stuck
    // on "No changes". Require the dirty state to stick and re-apply if it was reverted.
    async function selectDateRangeUntilDirty(insight: InsightPage, label: string): Promise<void> {
        await expect(async () => {
            await insight.trends.selectDateRange(label)
            await expect(insight.saveButton).not.toContainText('No changes', { timeout: 2000 })
            await insight.page.waitForTimeout(300)
            await expect(insight.saveButton).not.toContainText('No changes', { timeout: 500 })
            await expect(insight.saveButton).toBeEnabled({ timeout: 500 })
        }).toPass({ timeout: 30000 })
    }

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
            await insight.trends.expectRowTotal('Chrome', pageviews.expected.chromeTotal)
            await insight.trends.expectRowTotal('Firefox', pageviews.expected.firefoxTotal)
            await insight.trends.hoverChartAt(0.5, 0.5)
            const multiText = await insight.trends.tooltip.textContent()
            expect(multiText).toContain('Chrome')
            expect(multiText).toContain('Firefox')
        })

        await test.step('navigate away and verify no orphaned tooltip', async () => {
            await insight.goToList()
            await expect(page.getByRole('heading', { name: 'Product analytics', level: 1 })).toBeVisible()
            await expect(insight.trends.tooltip).toHaveCount(0, { timeout: 3000 })
        })
    })

    test('Save an insight, make changes, discard them, and save a copy', async ({ page }) => {
        test.setTimeout(90_000)
        const insight = new InsightPage(page)
        const name = randomString('lifecycle')

        await test.step('create and save an insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(name)
            await insight.save()
        })

        await test.step('enter edit mode and verify button states', async () => {
            await insight.edit()
            await expect(insight.saveButton).toBeVisible()
            await expect(insight.saveButton).toBeDisabled()
            await expect(insight.editButton).not.toBeVisible()
        })

        await test.step('change date range then discard and verify revert', async () => {
            await selectDateRangeUntilDirty(insight, 'Last 30 days')
            await expect(insight.trends.dateRangeButton).toContainText('Last 30 days')
            await expect(insight.saveButton).toBeEnabled()
            await insight.discard()
            await expect(insight.editButton).toBeVisible()
            await insight.trends.waitForChart()
            // Handle race where DateFilter state is lost during mode transition remount
            await expect(insight.trends.dateRangeButton).toContainText('Last 7 days', { timeout: 10_000 })
        })

        await test.step('edit again, make a change, and save', async () => {
            await insight.edit()
            await selectDateRangeUntilDirty(insight, 'Last 14 days')
            await insight.save()
            await expect(insight.trends.dateRangeButton).toContainText('Last 14 days')
        })

        await test.step('switch insight type to Funnels and back, then discard', async () => {
            await insight.edit()
            await page.locator('[data-attr="insight-funnels-tab"]').click()
            await expect(insight.activeTab).toContainText('Funnels')
            await page.locator('[data-attr="insight-trends-tab"]').click()
            await expect(insight.activeTab).toContainText('Trends')
            await insight.trends.waitForChart()
            await expect(insight.trends.dateRangeButton).toContainText('Last 14 days')
            await insight.discard()
        })

        const copyName = randomString('copy')
        await test.step('save as new and verify URL changes', async () => {
            const originalUrl = page.url()
            await insight.edit()
            await insight.saveAsNew(copyName)
            expect(page.url()).not.toBe(originalUrl)
            await expect(insight.topBarName).toContainText(copyName, { timeout: 10000 })
        })

        await test.step('navigate to list and verify both insights exist', async () => {
            await insight.goToList()
            await expect(page.locator('table')).toBeVisible()
            await expect(page.getByRole('link', { name })).toBeVisible()
            await expect(page.getByRole('link', { name: copyName })).toBeVisible()
        })
    })

    test('Export insight data as CSV and XLSX', async ({ page }) => {
        const insight = new InsightPage(page)
        await insight.goToNewTrends()
        await insight.trends.waitForChart()
        await insight.trends.waitForDetailsTable()

        await test.step('export as CSV', async () => {
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
