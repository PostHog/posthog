import { NotebookPage } from '../../page-models/notebookPage'
import { randomString } from '../../utils'
import { pageviews } from '../../utils/test-data'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

const events = pageviews.events

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
            // Dismiss any modal/overlay that may remain after node removal
            await page.keyboard.press('Escape')
            await expect(page.locator('.ReactModal__Overlay')).toHaveCount(0, { timeout: 5000 })
        })

        await test.step('type text content in the notebook', async () => {
            const savePromise = notebook.waitForSave()
            await notebook.focusNewParagraphAtEnd()
            await page.keyboard.type(textContent)
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
