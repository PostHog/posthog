import { InsightType } from '~/types'

import { DashboardPage } from '../../page-models/dashboardPage'
import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Insight creation', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Funnels: configure multi-step funnel, verify visualization, save and persist', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Funnels insight and verify active tab', async () => {
            await insight.goToNewInsight(InsightType.FUNNELS)
            await expect(insight.activeTab).toContainText('Funnels')
        })

        await test.step('add a second step and wait for computation', async () => {
            await page.getByTestId('add-action-event-button-empty-state').click()
            await insight.funnels.waitForChart()
        })

        await test.step('verify funnel visualization', async () => {
            await expect(insight.funnels.stepBars).toHaveCount(2)
            await expect(page.getByText('Total conversion rate:')).toBeVisible()
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })

    test('Retention: verify table and chart render, save and persist', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Retention insight and verify active tab', async () => {
            await insight.goToNewInsight(InsightType.RETENTION)
            await expect(insight.activeTab).toContainText('Retention')
            await insight.retention.waitForChart()
        })

        await test.step('verify retention table renders with cohort rows', async () => {
            const rows = insight.retention.table.locator('tr')
            const rowCount = await rows.count()
            expect(rowCount).toBeGreaterThanOrEqual(1)
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })

    test('Paths: verify page renders, save and persist', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Paths insight and verify active tab', async () => {
            await insight.goToNewInsight(InsightType.PATHS)
            await expect(insight.activeTab).toContainText('Paths')
            await insight.paths.waitForChart()
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })

    test('Stickiness: verify chart and save', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Stickiness insight and wait for result', async () => {
            await insight.goToNewInsight(InsightType.STICKINESS)
            await expect(insight.activeTab).toContainText('Stickiness')
            await insight.stickiness.waitForChart()
        })

        await test.step('verify details table', async () => {
            await insight.stickiness.waitForDetailsTable()
            const tableText = await insight.stickiness.detailsTable.textContent()
            expect(tableText?.toLowerCase()).toContain('day')
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })

    test('Lifecycle: verify chart and lifecycle toggles, save and persist', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new Lifecycle insight and wait for result', async () => {
            await insight.goToNewInsight(InsightType.LIFECYCLE)
            await expect(insight.activeTab).toContainText('Lifecycle')
            await insight.lifecycle.waitForChart()
        })

        await test.step('verify lifecycle toggles section is present', async () => {
            await expect(page.getByText('Lifecycle Toggles')).toBeVisible()
        })

        await test.step('save and verify view mode', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })
    })

    test('SQL / HogQL: write query, execute and verify results', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to SQL editor and verify it renders', async () => {
            await insight.goToSql()
            await insight.sql.waitForChart()
        })

        await test.step('write and execute a HogQL query', async () => {
            await insight.sql.writeQuery(
                [
                    'SELECT',
                    '  count() AS total_pageviews,',
                    '  toDate(timestamp) AS day',
                    'FROM events',
                    "WHERE event = '$pageview'",
                    'GROUP BY day',
                    'ORDER BY day DESC',
                    'LIMIT 10',
                ].join('\n')
            )
            await insight.sql.run()
        })

        await test.step('verify results appear', async () => {
            await expect(page.getByText('Showing 10 rows')).toBeVisible()
            await expect(page.getByText('total_pageviews').first()).toBeVisible()
        })
    })

    test('Save to Dashboard: create Trends insight and add to a new dashboard', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboard = new DashboardPage(page)

        await test.step('create and save a Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('add insight to a new dashboard', async () => {
            await dashboard.addToNewDashboardFromInsightPage()
            await expect(page).toHaveURL(/\/dashboard\//)
            await expect(page.locator('.InsightCard canvas').first()).toBeVisible()
        })
    })
})
