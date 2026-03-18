import { InsightPage } from '../../page-models/insightPage'
import { NotebookPage } from '../../page-models/notebookPage'
import { randomString } from '../../utils'
import { createEvent, daysAgo } from '../../utils/event-data'
import { PlaywrightSetupEvent } from '../../utils/playwright-setup'
import { pageviews } from '../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

const STEP_1 = 'funnel_step_one'
const STEP_2 = 'funnel_step_two'
const STEP_3 = 'funnel_step_three'

function generateFunnelEvents(): PlaywrightSetupEvent[] {
    const chromeUsers = (n: number): string => `chrome-user-${n}`
    const firefoxUsers = (n: number): string => `firefox-user-${n + 10}`
    const chrome = { $browser: 'Chrome' }
    const firefox = { $browser: 'Firefox' }

    return [
        ...createEvent({ event: STEP_1, user: chromeUsers, timestamp: daysAgo(5), properties: chrome }).repeat(10),
        ...createEvent({ event: STEP_1, user: firefoxUsers, timestamp: daysAgo(5), properties: firefox }).repeat(10),
        ...createEvent({ event: STEP_2, user: chromeUsers, timestamp: daysAgo(4), properties: chrome }).repeat(10),
        ...createEvent({ event: STEP_3, user: chromeUsers, timestamp: daysAgo(3), properties: chrome }).repeat(5),
    ]
}

const events = [...pageviews.events, ...generateFunnelEvents()]

test.describe('Notebooks', () => {
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

    test('Add a trend insight, expand it, verify data, and filter by date range', async ({ page }) => {
        const notebook = new NotebookPage(page)
        const notebookName = randomString('nb-trends')
        const boldNumber = page.getByTestId('bold-number-value')

        await test.step('create a notebook and add a Trend insight', async () => {
            await notebook.createNew(notebookName)
            await notebook.addInsightViaSlashCommand('Trend')
            await expect(notebook.insightNodes).toHaveCount(1)
        })

        await test.step('expand the insight and switch to Number chart', async () => {
            await notebook.expandInsightNode(0)
            await notebook.waitForInsightLoad()
            await expect(page.getByTestId('trend-element-subject-0').first()).toHaveText('Pageview')
            await notebook.selectChartType(/^Number/)
        })

        await test.step('verify total pageview count is 38', async () => {
            await expect(boldNumber).toContainText(pageviews.expected.total)
        })

        await test.step('change date range to Last 24 hours and verify total changes to 2', async () => {
            await notebook.selectDateRange('Last 24 hours')
            await expect(boldNumber).toContainText('2')
        })

        await test.step('change back to Last 7 days and verify total returns to 38', async () => {
            await notebook.selectDateRange('Last 7 days')
            await expect(boldNumber).toContainText(pageviews.expected.total)
        })

        await test.step('verify notebook appears on the list', async () => {
            await notebook.goToList()
            await expect(notebook.getNotebookRowByName(notebookName)).toBeVisible()
        })
    })

    test('Add a funnel insight, configure steps, and verify conversion rates', async ({ page }) => {
        test.setTimeout(60_000)
        const notebook = new NotebookPage(page)
        const insight = new InsightPage(page)
        const notebookName = randomString('nb-funnels')

        await test.step('create a notebook and add a Funnel insight', async () => {
            await notebook.createNew(notebookName)
            await notebook.addInsightViaSlashCommand('Funnel')
            await expect(notebook.insightNodes).toHaveCount(1)
        })

        await test.step('expand the insight and configure 3 funnel steps', async () => {
            await notebook.expandInsightNode(0)

            await insight.funnels.selectStepEvent(0, STEP_1)
            await page.getByRole('button', { name: 'Add step' }).click()
            await page.keyboard.press('Escape')
            await insight.funnels.selectStepEvent(1, STEP_2)
            await page.getByRole('button', { name: 'Add step' }).click()
            await page.keyboard.press('Escape')
            await insight.funnels.selectStepEvent(2, STEP_3)
            await insight.funnels.waitForChart()
        })

        await test.step('verify step counts: 20 → 10 → 5 and conversion rates', async () => {
            const step1 = insight.funnels.stepLegend(0)
            await expect(step1).toContainText('20')
            await expect(step1).toContainText(STEP_1)

            const step2 = insight.funnels.stepLegend(1)
            await expect(step2).toContainText('10')
            await expect(step2).toContainText('50')

            const step3 = insight.funnels.stepLegend(2)
            await expect(step3).toContainText('5')
            await expect(step3).toContainText('25')
        })
    })

    test('Remove an insight from a notebook and verify text persists', async ({ page }) => {
        const notebook = new NotebookPage(page)
        const notebookName = randomString('nb-remove')
        const textContent = randomString('some-text')

        await test.step('create a notebook and add a Trend insight', async () => {
            await notebook.createNew(notebookName)
            await notebook.addInsightViaSlashCommand('Trend')
            await expect(notebook.insightNodes).toHaveCount(1)
        })

        await test.step('remove the insight from the notebook', async () => {
            await notebook.removeInsightNode()
            await expect(notebook.insightNodes).toHaveCount(0)
        })

        await test.step('type text content in the notebook', async () => {
            const savePromise = notebook.waitForSave()
            await notebook.editor.click()
            await notebook.editor.press('End')
            await notebook.editor.press('Enter')
            await notebook.editor.pressSequentially(textContent)
            await expect(notebook.editor).toContainText(textContent)
            await savePromise
        })

        await test.step('reload and verify the text persisted', async () => {
            await page.reload({ waitUntil: 'domcontentloaded' })
            await expect(notebook.editor).toContainText(textContent, { timeout: 15000 })
        })
    })

    test('Delete a notebook from the list', async ({ page }) => {
        const notebook = new NotebookPage(page)
        const notebookName = randomString('nb-delete')

        await test.step('create a new notebook', async () => {
            await notebook.createNew(notebookName)
            await expect(notebook.titleHeading).toContainText(notebookName)
        })

        await test.step('navigate to list and verify notebook exists', async () => {
            await notebook.goToList()
            await expect(notebook.getNotebookRowByName(notebookName)).toBeVisible()
        })

        await test.step('delete the notebook via the more menu', async () => {
            await notebook.deleteFromList(notebookName)
        })

        await test.step('verify the notebook is gone from the list', async () => {
            await expect(notebook.getNotebookRowByName(notebookName)).not.toBeVisible()
        })
    })
})
