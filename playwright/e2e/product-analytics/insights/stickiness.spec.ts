import { InsightType } from '~/types'

import { InsightPage } from '../../../page-models/insightPage'
import { stickinessPageviews, stickinessWithBreakdown } from '../../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const pv = stickinessPageviews.expected
const bd = stickinessWithBreakdown.expected

const events = [...stickinessPageviews.events, ...stickinessWithBreakdown.events]

test.describe('Stickiness insights', () => {
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

    test('View default stickiness and verify day bucket values', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to new stickiness insight', async () => {
            await insight.goToNewInsight(InsightType.STICKINESS)
            await expect(insight.activeTab).toContainText('Stickiness')
            await insight.stickiness.waitForChart()
        })

        await test.step('verify defaults are Pageview, Unique users, Last 7 days', async () => {
            await expect(insight.stickiness.firstSeries).toContainText('Pageview')
            await expect(page.getByText('Unique users')).toBeVisible()
            await expect(page.getByText('Last 7 days')).toBeVisible()
        })

        await test.step('verify stickiness day bucket values in details table', async () => {
            await insight.stickiness.waitForDetailsTable()

            const day1 = await insight.stickiness.details.row('Pageview').column('Day 1')
            expect(day1).toContain(`${pv.day1.percent.toFixed(1)}%`)
            expect(day1).toContain(`(${pv.day1.users})`)

            const day2 = await insight.stickiness.details.row('Pageview').column('Day 2')
            expect(day2).toContain(`${pv.day2.percent.toFixed(1)}%`)
            expect(day2).toContain(`(${pv.day2.users})`)

            const day3 = await insight.stickiness.details.row('Pageview').column('Day 3')
            expect(day3).toContain(`${pv.day3.percent.toFixed(1)}%`)
            expect(day3).toContain(`(${pv.day3.users})`)

            const day5 = await insight.stickiness.details.row('Pageview').column('Day 5')
            expect(day5).toContain(`${pv.day5.percent.toFixed(1)}%`)
            expect(day5).toContain(`(${pv.day5.users})`)
        })
    })

    test('Switch to custom event and verify stickiness values', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to stickiness and switch to custom event', async () => {
            await insight.goToNewInsight(InsightType.STICKINESS)
            await expect(insight.activeTab).toContainText('Stickiness')
            await insight.stickiness.waitForChart()
            await insight.stickiness.selectEvent(0, stickinessWithBreakdown.eventName)
            await insight.stickiness.waitForChart()
        })

        await test.step('verify custom event stickiness distribution', async () => {
            await insight.stickiness.waitForDetailsTable()

            const day1 = await insight.stickiness.details.row(stickinessWithBreakdown.eventName).column('Day 1')
            expect(day1).toContain(`${bd.day1.percent.toFixed(1)}%`)
            expect(day1).toContain(`(${bd.day1.users})`)

            const day3 = await insight.stickiness.details.row(stickinessWithBreakdown.eventName).column('Day 3')
            expect(day3).toContain(`${bd.day3.percent.toFixed(1)}%`)
            expect(day3).toContain(`(${bd.day3.users})`)

            const day2 = await insight.stickiness.details.row(stickinessWithBreakdown.eventName).column('Day 2')
            expect(day2).toContain(`${bd.day2.percent.toFixed(1)}%`)
            expect(day2).toContain(`(${bd.day2.users})`)
        })

        await test.step('switch back to Pageview and verify original distribution', async () => {
            await insight.stickiness.selectEvent(0, 'Pageview')
            await insight.stickiness.waitForChart()
            await insight.stickiness.waitForDetailsTable()

            const day1 = await insight.stickiness.details.row('Pageview').column('Day 1')
            expect(day1).toContain(`${pv.day1.percent.toFixed(1)}%`)
            expect(day1).toContain(`(${pv.day1.users})`)

            const day5 = await insight.stickiness.details.row('Pageview').column('Day 5')
            expect(day5).toContain(`${pv.day5.percent.toFixed(1)}%`)
            expect(day5).toContain(`(${pv.day5.users})`)
        })
    })

    test('Add second series and verify both rows in details table', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to stickiness with custom event', async () => {
            await insight.goToNewInsight(InsightType.STICKINESS)
            await expect(insight.activeTab).toContainText('Stickiness')
            await insight.stickiness.waitForChart()
            await insight.stickiness.selectEvent(0, stickinessWithBreakdown.eventName)
            await insight.stickiness.waitForChart()
        })

        await test.step('add second series with Pageview and verify both rows', async () => {
            await insight.stickiness.addSeries()
            await insight.stickiness.selectEvent(1, 'Pageview')
            await insight.stickiness.waitForChart()
            await insight.stickiness.waitForDetailsTable()

            const customDay1 = await insight.stickiness.details.row(stickinessWithBreakdown.eventName).column('Day 1')
            expect(customDay1).toContain(`${bd.day1.percent.toFixed(1)}%`)

            const pageviewDay1 = await insight.stickiness.details.row('Pageview').column('Day 1')
            expect(pageviewDay1).toContain(`${pv.day1.percent.toFixed(1)}%`)
        })
    })

    test('Change date range and toggle comparison', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to stickiness insight', async () => {
            await insight.goToNewInsight(InsightType.STICKINESS)
            await expect(insight.activeTab).toContainText('Stickiness')
            await insight.stickiness.waitForChart()
        })

        await test.step('change date range to Last 14 days and verify data persists', async () => {
            await insight.stickiness.selectDateRange('Last 14 days')
            await insight.stickiness.waitForDetailsTable()

            const day1 = await insight.stickiness.details.row('Pageview').column('Day 1')
            expect(day1).toContain(`${pv.day1.percent.toFixed(1)}%`)
            expect(day1).toContain(`(${pv.day1.users})`)

            const day3 = await insight.stickiness.details.row('Pageview').column('Day 3')
            expect(day3).toContain(`${pv.day3.percent.toFixed(1)}%`)
            expect(day3).toContain(`(${pv.day3.users})`)
        })

        await test.step('enable comparison and verify no NaN in table', async () => {
            await insight.stickiness.selectComparison('Compare to previous period')
            await insight.stickiness.waitForDetailsTable()
            const tableText = await insight.stickiness.detailsTable.textContent()
            expect(tableText).not.toContain('NaN')
            expect(tableText).not.toContain('undefined')
        })

        await test.step('disable comparison and verify values restored', async () => {
            await insight.stickiness.selectComparison('No comparison between periods')
            await expect(insight.stickiness.comparisonButton).toContainText('No comparison')
            await insight.stickiness.waitForDetailsTable()

            const day1 = await insight.stickiness.details.row('Pageview').column('Day 1')
            expect(day1).toContain(`${pv.day1.percent.toFixed(1)}%`)
            expect(day1).toContain(`(${pv.day1.users})`)
        })
    })
})
