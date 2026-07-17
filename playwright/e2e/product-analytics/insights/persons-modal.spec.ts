import { InsightPage } from '../../../page-models/insightPage'
import { pageviews } from '../../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

const events = [...pageviews.events]

test.describe('Persons modal', () => {
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

    test('"View events" navigates to the events explorer, not a Trends insight', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('open a Number chart and click the value to open the persons modal', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            // A Number chart exposes a single clickable aggregated value — a far more deterministic
            // drill-down target than a line-graph data point.
            await insight.trends.selectChartType(/^Number/)
            await expect(insight.trends.boldNumber).toContainText(pageviews.expected.total)
            await insight.trends.boldNumber.click()
            await expect(insight.personsModal).toBeVisible()
        })

        await test.step('"View events" opens the events explorer', async () => {
            await expect(insight.personsModalViewEventsButton).toBeVisible()
            const popupPromise = page.context().waitForEvent('page')
            await insight.personsModalViewEventsButton.click()
            const eventsTab = await popupPromise
            await expect(eventsTab).toHaveURL(/\/activity\/explore/)
        })
    })
})
