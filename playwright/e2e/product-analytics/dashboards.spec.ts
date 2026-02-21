import { DashboardPage } from '../../page-models/dashboardPage'
import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Dashboards', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Can create a new dashboard with an insight', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const dashboardName = randomString('dash-edit')

        await test.step('create a dashboard', async () => {
            await dashboard.createNew(dashboardName)
        })

        await test.step('add the insight to the dashboard', async () => {
            await dashboard.addInsightToNewDashboard()
            await expect(dashboard.insightCards).toBeVisible()
        })
    })

    test('Editing an insight updates the dashboard tile', async ({ page }) => {
        const dashboard = new DashboardPage(page)
        const insight = new InsightPage(page)
        const updatedName = randomString('dash-updated')
        let dashboardUrl: string

        await test.step('create a dashboard with an insight', async () => {
            await dashboard.createNew()
            await dashboard.addInsightToNewDashboard()
            await expect(dashboard.insightCards).toBeVisible()
            dashboardUrl = page.url()
        })

        await test.step('select to edit an insight', async () => {
            await dashboard.openFirstTileMenu()
            await dashboard.selectTileMenuOption('Edit')
            await expect(page).toHaveURL(/edit/)
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
            await expect(dashboard.insightCards.first().locator('[data-attr="insight-card-title"]')).toContainText(
                updatedName
            )
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
            await expect(card.locator('canvas')).toBeVisible()
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

    test('Duplicating a dashboard preserves text cards, date filter, and variables', async ({ page, request }) => {
        const dashboard = new DashboardPage(page)
        const cardText = randomString('card-text')
        let sourceDashboardUrl: string

        // Create a variable and insight via API so we can test variable preservation
        const baseURL =
            page
                .context()
                .pages()[0]
                ?.url()
                .match(/^https?:\/\/[^/]+/)?.[0] ?? 'http://localhost:8010'
        const headers = { Authorization: `Bearer ${workspace!.personal_api_key}` }
        const teamId = workspace!.team_id

        const variableRes = await request.post(`${baseURL}/api/environments/${teamId}/insight_variables/`, {
            headers,
            data: { name: 'Test Var', type: 'Number', default_value: 10 },
        })
        const variable = await variableRes.json()

        const insightRes = await request.post(`${baseURL}/api/projects/${teamId}/insights/`, {
            headers,
            data: {
                name: 'Variable insight',
                query: {
                    kind: 'DataVisualizationNode',
                    source: {
                        kind: 'HogQLQuery',
                        query: `SELECT {variables.${variable.code_name}}`,
                        variables: {
                            [variable.id]: { code_name: variable.code_name, variableId: variable.id },
                        },
                    },
                    chartSettings: {},
                    tableSettings: {},
                },
            },
        })
        const insight = await insightRes.json()

        await test.step('create an empty dashboard and add a text card', async () => {
            await dashboard.createNew()
            await expect(dashboard.insightCards).not.toBeVisible()
            await dashboard.addTextCard(cardText)
        })

        await test.step('add the variable insight and set date filter', async () => {
            sourceDashboardUrl = page.url()
            const dashboardId = sourceDashboardUrl.match(/\/dashboard\/(\d+)/)?.[1]

            // Add the variable insight to the dashboard via the insight's dashboards field
            await request.patch(`${baseURL}/api/projects/${teamId}/insights/${insight.id}/`, {
                headers,
                data: {
                    dashboards: [parseInt(dashboardId!)],
                },
            })

            // Set a dashboard-level variable override via API
            await request.patch(`${baseURL}/api/projects/${teamId}/dashboards/${dashboardId}/`, {
                headers,
                data: {
                    variables: {
                        [variable.id]: { code_name: variable.code_name, variableId: variable.id, value: 42 },
                    },
                },
            })

            // Reload so the new tile and variable appear in the UI
            await page.reload({ waitUntil: 'domcontentloaded' })
            await expect(dashboard.insightCards).toBeVisible()

            await dashboard.setDateFilter('Last 30 days')
        })

        await test.step('duplicate the dashboard', async () => {
            await dashboard.duplicate()
            await expect(page).not.toHaveURL(sourceDashboardUrl)
        })

        await test.step('verify duplicated dashboard has the text card', async () => {
            await expect(dashboard.textCards).toBeVisible()
            await expect(dashboard.textCards).toContainText(cardText)
        })

        await test.step('verify duplicated dashboard has the date filter preserved', async () => {
            await expect(dashboard.dateFilter).toContainText('Last 30 days')
        })

        await test.step('verify duplicated dashboard has the variable override preserved', async () => {
            // The variable insight tile should be present on the duplicated dashboard
            const variableCard = await dashboard.findCardByTitle('Variable insight')
            await expect(variableCard).toBeVisible()

            // Verify persisted_variables via API on the duplicated dashboard
            const dupDashboardId = page.url().match(/\/dashboard\/(\d+)/)?.[1]
            const dupRes = await request.get(`${baseURL}/api/projects/${teamId}/dashboards/${dupDashboardId}/`, {
                headers,
            })
            const dupDashboard = await dupRes.json()
            expect(dupDashboard.variables?.[variable.id]?.value).toBe(42)
        })
    })

    test('Changing a variable override on a dashboard updates the tile', async ({ page }) => {
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
            await dialog.getByRole('button', { name: 'Save' }).click()
            await expect(dialog).not.toBeVisible()
        })

        await test.step('write query, run, and save as insight', async () => {
            const editor = page.locator('.monaco-editor').first()
            await editor.click()
            await page.keyboard.press('Meta+a')
            await page.keyboard.type('SELECT {variables.test_number}', { delay: 10 })

            await page.getByRole('button', { name: 'Run' }).click()
            await expect(page.getByRole('button', { name: 'Create insight' })).toBeEnabled({ timeout: 30000 })
            await page.getByRole('button', { name: 'Create insight' }).click()

            await page.getByRole('button', { name: 'Save insight' }).click()
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
            await expect(page).toHaveURL(/\/dashboard$/)
            await expect(page.getByText('Not found')).not.toBeVisible()
            await expect(page.getByText(dashboardName)).not.toBeVisible()
        })
    })

    test('Creating a dashboard from a template populates tiles', async ({ page }) => {
        const dashboard = new DashboardPage(page)

        await test.step('create a dashboard from a template', async () => {
            await dashboard.createFromTemplate()
        })

        await test.step('verify the template dashboard has tiles', async () => {
            await expect(dashboard.insightCards.first()).toBeVisible({ timeout: 30000 })

            const tileCount = await dashboard.insightCards.count()
            expect(tileCount).toBeGreaterThan(0)
        })
    })
})
