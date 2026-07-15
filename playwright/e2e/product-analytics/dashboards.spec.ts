import { Page } from '@playwright/test'

import { DashboardPage } from '../../page-models/dashboardPage'
import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

async function createSavedTrendsInsight(page: Page, insightName: string): Promise<void> {
    const insight = new InsightPage(page)

    await insight.goToNewTrends()
    await insight.trends.waitForChart()
    await insight.editName(insightName)
    await insight.save()
    await expect(insight.editButton).toBeVisible()
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
            await createSavedTrendsInsight(page, insightName)
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
})

test.describe('Dashboard duplication', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            insight_variables: [{ name: 'Test Var', type: 'Number', default_value: 10 }],
            insights: [
                {
                    name: 'Variable insight',
                    query: {
                        kind: 'DataVisualizationNode',
                        source: { kind: 'HogQLQuery', query: 'SELECT {variables.test_var}' },
                        chartSettings: {},
                        tableSettings: {},
                    },
                    variable_indexes: [0],
                },
            ],
            dashboards: [
                {
                    name: 'Duplication source',
                    insight_indexes: [0],
                    variable_overrides: { '0': 42 },
                },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Duplicating a dashboard preserves text cards, date filter, and variables', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const cardText = randomString('card-text')
        const seededDashboardId = workspace!.created_dashboards![0].id
        let sourceDashboardUrl: string

        await test.step('navigate to seeded dashboard and add a text card', async () => {
            await page.goto(`/project/${workspace!.team_id}/dashboard/${seededDashboardId}`)
            await expect(dashboard.insightCards).toBeVisible()
            await dashboard.addTextCard(cardText)
        })

        await test.step('set date filter', async () => {
            sourceDashboardUrl = page.url()
            await dashboard.setDateFilter('Last 30 days')
        })

        await test.step('duplicate the dashboard', async () => {
            await dashboard.duplicate()
            await expect(page).not.toHaveURL(sourceDashboardUrl)
        })

        await test.step('verify duplicated dashboard preserves text card, date filter, and variable override', async () => {
            await expect(dashboard.textCards).toBeVisible()
            await expect(dashboard.textCards).toContainText(cardText)
            await expect(dashboard.dateFilter).toContainText('Last 30 days')
            await expect(dashboard.variableButtons.first()).toContainText('42')
        })
    })
})

test.describe('Dashboard link variable and filter overrides', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            insight_variables: [{ name: 'Test Var', type: 'Number', default_value: 10 }],
            insights: [
                {
                    name: 'Variable insight',
                    query: {
                        kind: 'DataVisualizationNode',
                        source: { kind: 'HogQLQuery', query: 'SELECT {variables.test_var}' },
                        chartSettings: {},
                        tableSettings: {},
                    },
                    variable_indexes: [0],
                },
            ],
            dashboards: [
                {
                    name: 'URL query variables seed',
                    insight_indexes: [0],
                    variable_overrides: { '0': 42 },
                    filters: { date_from: '-30d' },
                },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Opening a shared dashboard link applies variable and filter overrides from the URL on first load', async ({
        page,
    }) => {
        const dashboard = new DashboardPage(page)
        const seededDashboardId = workspace!.created_dashboards![0].id
        const urlOverride = 77
        const searchParams = new URLSearchParams()
        searchParams.set('query_variables', JSON.stringify({ test_var: urlOverride }))
        searchParams.set('query_filters', JSON.stringify({ date_from: '-7d' }))

        await page.goto(`/project/${workspace!.team_id}/dashboard/${seededDashboardId}?${searchParams.toString()}`, {
            waitUntil: 'domcontentloaded',
        })

        await expect(dashboard.insightCards).toBeVisible()
        await expect(dashboard.variableButtons.first()).toContainText(String(urlOverride))
        await expect(dashboard.dateFilter).toContainText('Last 7 days')
        await expect(dashboard.overridesBanner).toBeVisible()
    })
})
