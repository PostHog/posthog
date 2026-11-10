import { InsightType } from '~/types'

import { InsightPage } from '../../../page-models/insightPage'
import { stickinessPageviews } from '../../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const pv = stickinessPageviews.expected

const events = stickinessPageviews.events

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
})
