import { InsightType } from '~/types'

import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

// Dashboard override tests for retention cards live in dashboard-overrides.spec.ts

test.describe('Retention', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Create a retention insight and configure it', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new retention insight and verify table renders', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
            await expect(insight.retention.tableHeaders.first()).toContainText('Cohort')
            const rowCount = await insight.retention.tableRows.count()
            expect(rowCount).toBeGreaterThanOrEqual(2)
        })

        await test.step('change period from Day to Week', async () => {
            await insight.retention.selectPeriod('weeks')
            const headerTexts = await insight.retention.tableHeaders.allTextContents()
            const weekHeaders = headerTexts.filter((h) => /Week/i.test(h))
            expect(weekHeaders.length).toBeGreaterThanOrEqual(1)
            const rowCount = await insight.retention.tableRows.count()
            expect(rowCount).toBeGreaterThanOrEqual(2)
        })

        await test.step('toggle to cumulative retention', async () => {
            await insight.retention.toggleCumulative()
        })

        await test.step('add a breakdown by Browser', async () => {
            await insight.retention.addBreakdown('Browser')
        })

        await test.step('verify breakdown added section headers', async () => {
            const sectionCount = await insight.retention.sectionHeaders.count()
            expect(sectionCount).toBeGreaterThanOrEqual(1)
            const rowCount = await insight.retention.tableRows.count()
            expect(rowCount).toBeGreaterThanOrEqual(2)
        })

        await test.step('verify line chart renders', async () => {
            await expect(insight.retention.chart).toBeVisible()
            await expect(insight.retention.chart.locator('canvas')).toBeVisible()
        })
    })

    test('Explore retention data by hovering and clicking into cohorts', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a retention insight', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
            await expect(insight.retention.chart.locator('canvas')).toBeVisible()
        })

        await test.step('hover over a point on the line graph and verify tooltip', async () => {
            await insight.retention.hoverChartAt(0.15, 0.5)
            await expect(insight.retention.tooltip).toBeVisible()
            const text = await insight.retention.tooltip.textContent()
            expect(text).not.toContain('NaN')
            expect(text).not.toContain('undefined')
        })

        await test.step('hover over a different point further along', async () => {
            await insight.retention.hoverChartAt(0.5, 0.5)
            await expect(insight.retention.tooltip).toBeVisible()
            const text = await insight.retention.tooltip.textContent()
            expect(text).not.toContain('NaN')
            expect(text).not.toContain('undefined')
        })

        await test.step('click a cohort row to open the persons modal', async () => {
            await insight.retention.clickCohortRow(0)
        })

        await test.step('verify persons modal shows people', async () => {
            const personLinks = insight.retention.personsModal.locator('[data-attr="retention-person-link"]')
            await expect(personLinks.first()).toBeVisible({ timeout: 15000 })
        })

        await test.step('close modal and verify table is intact', async () => {
            await insight.retention.closePersonsModal()
            await expect(insight.retention.table).toBeVisible()
            const rowCount = await insight.retention.tableRows.count()
            expect(rowCount).toBeGreaterThanOrEqual(2)
        })
    })

    test('Save a retention insight and manage alerts', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightName = randomString('retention-alerts')

        await test.step('create and save a retention insight', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
            await expect(page).not.toHaveURL(/\/new$/)
        })

        await test.step('open the alerts page from the side panel', async () => {
            await page.getByTestId('info-actions-panel').click()
            await expect(insight.retention.alertsButton).toBeVisible()
            await insight.retention.alertsButton.click()
            await expect(page).toHaveURL(/\/alerts/)
        })

        await test.step('verify alerts page loads', async () => {
            await expect(page.getByText('Manage alerts')).toBeVisible()
        })

        await test.step('navigate back and verify insight still displays', async () => {
            await page.goBack()
            await expect(insight.retention.table).toBeVisible()
            const rowCount = await insight.retention.tableRows.count()
            expect(rowCount).toBeGreaterThanOrEqual(2)
        })
    })

    test('Use custom retention brackets', async ({ page }) => {
        const insight = new InsightPage(page)
        let defaultColumnCount: number

        await test.step('create a retention insight', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await insight.retention.waitForChart()
        })

        await test.step('capture default column count', async () => {
            defaultColumnCount = await insight.retention.tableHeaders.count()
            expect(defaultColumnCount).toBeGreaterThanOrEqual(3)
        })

        await test.step('enable custom brackets', async () => {
            await insight.retention.enableCustomBrackets()
        })

        await test.step('set custom bracket values 1, 3, 7, 14', async () => {
            await insight.retention.setCustomBracket(0, 1)
            await insight.retention.setCustomBracket(1, 3)
            await insight.retention.setCustomBracket(2, 7)
            await insight.retention.addCustomBracket()
            await insight.retention.setCustomBracket(3, 14)
        })

        await test.step('verify column headers show custom ranges', async () => {
            // Custom brackets go through a 1000ms debounce, so wait for the
            // range headers (e.g. "Days 2-4") to appear in the table.
            await expect(insight.retention.tableHeaders.filter({ hasText: /\d+-\d+/ }).first()).toBeVisible({
                timeout: 15000,
            })
            const headerTexts = await insight.retention.tableHeaders.allTextContents()
            expect(headerTexts).toContain('Day 0')
        })

        await test.step('verify table still has data rows', async () => {
            const rowCount = await insight.retention.tableRows.count()
            expect(rowCount).toBeGreaterThanOrEqual(2)
        })

        await test.step('disable custom brackets and verify default columns return', async () => {
            await insight.retention.disableCustomBrackets()
            const columnCount = await insight.retention.tableHeaders.count()
            expect(columnCount).toBe(defaultColumnCount)
        })
    })
})
