import { Page } from '@playwright/test'

import { DashboardPage } from '../../page-models/dashboardPage'
import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

/**
 * Creates a saved Trends insight via the API (no UI interaction).
 * This avoids flakiness from chart rendering timeouts under CI load.
 */
async function createSavedTrendsInsight(
    page: Page,
    insightName: string,
    workspace: PlaywrightWorkspaceSetupResult
): Promise<void> {
    const response = await page.request.post(`/api/projects/${workspace.team_id}/insights/`, {
        headers: {
            Authorization: `Bearer ${workspace.personal_api_key}`,
            'Content-Type': 'application/json',
        },
        data: {
            name: insightName,
            query: {
                kind: 'InsightVizNode',
                source: {
                    kind: 'TrendsQuery',
                    series: [{ kind: 'EventsNode', event: '$pageview' }],
                },
            },
        },
    })
    expect(response.ok()).toBe(true)
}

test.describe('Dashboards', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Editing an insight updates the dashboard tile', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const insight = new InsightPage(page)
        const insightName = randomString('dash-trends')
        const updatedName = randomString('dash-updated')
        let dashboardUrl: string

        await test.step('create a saved Trends insight', async () => {
            await createSavedTrendsInsight(page, insightName, workspace!)
        })

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard(insightName)
            await expect(dashboard.insightCards).toBeVisible()
            dashboardUrl = page.url()
        })

        await test.step('select to edit an insight', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Edit')
            await expect(page).toHaveURL(/\/insights\/.+\/edit(?:\?|$)/)
        })

        await test.step('edit the insight name and save', async () => {
            // Wait for the insight to fully load before editing — the save button
            // shows "No changes" once the API response has been applied to the store.
            // Without this, a late-arriving loadInsightSuccess can overwrite the
            // local name change and leave the save button permanently disabled.
            await expect(insight.saveButton).toContainText('No changes')
            await insight.editName(updatedName)
            await expect(insight.topBarName).toContainText(updatedName)
            await expect(insight.saveButton).toBeEnabled()
            await insight.save()
        })

        await test.step('navigate to dashboard and verify the updated insight', async () => {
            await page.goto(dashboardUrl, { waitUntil: 'domcontentloaded' })
            await expect(page).toHaveURL(/\/dashboard\//)
            await expect(dashboard.insightCards.first()).toBeVisible()
            const updatedCard = await dashboard.findCardByTitle(updatedName)
            await expect(updatedCard.locator('[data-attr="insight-card-title"]')).toContainText(updatedName)
        })
    })

    test('Add insight to new dashboard and view it there', async ({ page }) => {
        const insight = new InsightPage(page)
        const dashboard = new DashboardPage(page)
        const insightName = randomString('add-to-dash')

        await test.step('create and save a Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('add insight to a new dashboard', async () => {
            await dashboard.addToNewDashboardFromInsightPage()
        })

        await test.step('verify insight is visible on the new dashboard', async () => {
            await expect(page).toHaveURL(/\/dashboard\//)
            const card = dashboard.insightCards.filter({ hasText: insightName })
            await expect(card).toBeVisible()
            await expect(card.locator('canvas[role="img"]')).toBeVisible()
        })
    })

    test('Can duplicate, rename, and remove dashboard tiles', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const newTileName = randomString('tile-name')

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard()
            await expect(dashboard.insightCards).toBeVisible()
        })

        await test.step('duplicate the tile', async () => {
            const titleLocator = dashboard.insightCards.first().getByTestId('insight-card-title')
            await expect(titleLocator).not.toContainText('Loading')
            const title = await titleLocator.textContent()
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Duplicate')

            const duplicateTile = page.getByText(`${title} (Copy)`)
            await duplicateTile.scrollIntoViewIfNeeded()
            await expect(duplicateTile).toBeVisible()
        })

        await test.step('rename the first tile', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Rename')

            const renameModal = page.locator('.LemonModal').filter({ has: page.getByTestId('insight-name') })
            await renameModal.getByTestId('insight-name').fill(newTileName)
            await renameModal.getByText('Submit').click()

            await expect(dashboard.insightCards.first().getByText(newTileName)).toBeVisible()
        })

        await test.step('remove the first tile', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Remove from dashboard')

            await expect(dashboard.insightCards.first().getByText(newTileName)).not.toBeVisible()
        })
    })

    test('Creating a SQL insight with a variable and overriding it on a dashboard', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const insight = new InsightPage(page)

        await test.step('open SQL editor and create a Number variable', async () => {
            await page.goto('/sql')
            await page.getByRole('button', { name: 'Variables' }).click()
            await page.getByRole('menuitem', { name: 'New variable' }).click()
            await page.getByRole('menuitem', { name: 'Number', exact: true }).click()

            const dialog = page.locator('.LemonModal').filter({ hasText: 'New Number variable' })
            await expect(dialog).toBeVisible()
            await dialog.getByRole('textbox', { name: 'Name' }).fill('Test Number')
            await dialog.getByRole('spinbutton').fill('5')

            // Saving the variable kicks off a reload of the insightVariables list, and the
            // editor can only substitute {variables.test_number} once that list has loaded.
            // Running the query before the reload returns sends the placeholder unresolved,
            // the backend errors with "Global variable not found: variables", and
            // "Save as insight" never enables. Wait for the reload before using the variable.
            const variablesReloaded = page.waitForResponse(
                (response) =>
                    response.url().includes('/insight_variables') &&
                    response.request().method() === 'GET' &&
                    response.ok()
            )
            await dialog.getByRole('button', { name: 'Save' }).click()
            await expect(dialog).not.toBeVisible()
            await variablesReloaded
        })

        await test.step('write query, run, and save as insight', async () => {
            const editor = page.locator('.monaco-editor').first()
            await editor.click()
            await page.keyboard.press('ControlOrMeta+a')
            // insertText() inserts the whole string at once, so Monaco's bracket
            // auto-close and autocomplete don't intercept the `{`/`}` mid-type and
            // produce a malformed query that leaves "Save as insight" disabled.
            await page.keyboard.insertText('SELECT {variables.test_number}')
            await page.keyboard.press('Escape')

            // The editor attaches the variable to the query through a short debounce, so a
            // fast first Run can execute before {variables.test_number} is substituted —
            // the query then errors with "Global variable not found: variables" and leaves
            // "Save as insight" disabled. Re-run until the variable resolves and the query
            // succeeds (a successful run is the only thing that enables "Save as insight").
            const saveAsInsight = page.getByRole('button', { name: 'Save as insight' })
            await expect(async () => {
                await page.getByRole('button', { name: 'Run' }).click()
                await expect(page.locator('[data-attr=sql-editor-output-pane-empty-state]')).not.toBeVisible()
                await expect(saveAsInsight).toBeEnabled({ timeout: 15000 })
            }).toPass({ timeout: 60000 })
            await saveAsInsight.click()

            const saveModal = page.locator('.LemonModal').filter({ hasText: 'Save as new insight' })
            await expect(saveModal).toBeVisible()
            await saveModal.getByPlaceholder('Please enter the new name').fill('Variable test insight')
            await saveModal.getByRole('button', { name: 'Submit' }).click()

            // After save, the SQL editor redirects to the insight view page
            await expect(page).toHaveURL(/\/insights\//)
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('add the insight to a new dashboard', async () => {
            await dashboard.addToNewDashboardFromInsightPage()
        })

        await test.step('verify the variable control shows the default value', async () => {
            await expect(page).toHaveURL(/\/dashboard\//)
            await dashboard.closeInfoPanel()
            await expect(dashboard.insightCards).toBeVisible()
            await expect(dashboard.variableButtons.first()).toContainText('5')
        })

        await test.step('change the variable value via the UI', async () => {
            await dashboard.setVariable('Test Number', 99)
        })

        await test.step('verify the variable button reflects the new value', async () => {
            await expect(dashboard.variableButtons.first()).toContainText('99')
        })
    })

    test('Deleting a dashboard navigates to the dashboards list', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const dashboardName = randomString('dash-delete')

        await test.step('create a dashboard', async () => {
            await dashboard.createNew(dashboardName)
            await expect(page).toHaveURL(/\/dashboard\/\d+/)
        })

        await test.step('delete the dashboard', async () => {
            await dashboard.deleteDashboard()
        })

        await test.step('verify navigation to dashboards list (not "Not found")', async () => {
            await expect(page).toHaveURL(/\/dashboard(#panel=[a-z]+)?$/)
            await expect(page.getByText('Not found')).not.toBeVisible()
            // Reload so the list is rebuilt from the server, which excludes deleted
            // dashboards. The in-memory dashboardsModel can keep a stale row visible
            // (the list selector doesn't filter `deleted`, and an in-flight load can
            // re-merge it after delayedDeleteDashboard prunes it), so an unscoped or
            // even table-scoped assertion against live state is racy. Scope to the
            // table to exclude the "deleted" toast, which also contains the name.
            await page.reload()
            await expect(page.getByTestId('dashboards-table')).toBeVisible()
            await expect(page.getByTestId('dashboards-table').getByText(dashboardName)).not.toBeVisible()
        })
    })

    test('Deleting an insight from dashboard redirects back', async ({ page }) => {
        test.setTimeout(120_000)
        const dashboard = new DashboardPage(page)
        const insight = new InsightPage(page)
        const insightName = randomString('dash-trends')

        await test.step('create a saved Trends insight', async () => {
            await createSavedTrendsInsight(page, insightName, workspace!)
        })

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard(insightName)
            await expect(dashboard.insightCards).toBeVisible()
        })

        await test.step('open the insight from the dashboard', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Edit')
            await expect(page).toHaveURL(/\/insights\/.+\/edit(?:\?|$)/)
            // Wait for the insight to fully load before interacting with the
            // side panel — InsightPanelDangerZone only renders the delete
            // button once the insight data is available in the store.
            await expect(insight.saveButton).toContainText('No changes')
        })

        await test.step('open the info panel and click delete', async () => {
            await insight.openInfoPanel()
            await insight.clickDeleteInsight()
            await expect(page.locator('.LemonModal').filter({ hasText: 'Delete insight?' })).toBeVisible()
        })

        await test.step('cancel the dialog and verify we stay on the insight', async () => {
            await insight.cancelDeleteDialog()
            await expect(page).toHaveURL(/edit/)
        })

        await test.step('click delete again and confirm', async () => {
            await insight.clickDeleteInsight()
            await insight.confirmDeleteDialog()
        })

        await test.step('verify redirect to the dashboard with no insight cards', async () => {
            await expect(page).toHaveURL(/\/dashboard\//)
            await expect(dashboard.insightCards).toHaveCount(0)
        })
    })
})

test.describe('Dashboard compact cards and inline editing', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Inline editing insight title via compact card popover', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const insightName = randomString('dash-trends')
        const updatedTitle = randomString('inline-title')

        await test.step('create a saved Trends insight', async () => {
            await createSavedTrendsInsight(page, insightName, workspace!)
        })

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard(insightName)
            await expect(dashboard.insightCards).toBeVisible()
        })

        await test.step('hover over the card to open the popover', async () => {
            await dashboard.hoverFirstCard()
            await expect(dashboard.popoverTitleField).toBeVisible()
        })

        await test.step('edit the title inline', async () => {
            await dashboard.editPopoverTitle(updatedTitle)
        })

        await test.step('verify toast and updated title', async () => {
            await expect(page.getByText('Insight updated')).toBeVisible()
            await expect(dashboard.insightCards.first().getByTestId('insight-card-title')).toContainText(updatedTitle)
        })

        await test.step('reload and verify title persisted', async () => {
            await page.reload({ waitUntil: 'domcontentloaded' })
            await expect(dashboard.insightCards.first().getByTestId('insight-card-title')).toContainText(updatedTitle)
        })
    })

    test('Inline editing insight description via compact card popover', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const insightName = randomString('dash-trends')
        const description = randomString('inline-desc')

        await test.step('create a saved Trends insight', async () => {
            await createSavedTrendsInsight(page, insightName, workspace!)
        })

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard(insightName)
            await expect(dashboard.insightCards).toBeVisible()
        })

        await test.step('hover over the card to open the popover', async () => {
            await dashboard.hoverFirstCard()
            await expect(dashboard.popoverDescriptionField).toBeVisible()
        })

        await test.step('edit the description inline', async () => {
            await dashboard.editPopoverDescription(description)
        })

        await test.step('verify toast', async () => {
            await expect(page.getByText('Insight updated')).toBeVisible()
        })

        await test.step('reload and verify description persisted', async () => {
            await page.reload({ waitUntil: 'domcontentloaded' })
            await dashboard.hoverFirstCard()
            await expect(dashboard.tilePopover.getByText(description)).toBeVisible()
        })
    })
})
