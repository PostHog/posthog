import { Page } from '@playwright/test'

import { SqlInsight } from '../page-models/insights/sqlInsight'
import { mockFeatureFlags } from '../utils/mockApi'
import { expect, test, PlaywrightWorkspaceSetupResult } from '../utils/workspace-test-base'

const BUILDER_FLAG = 'bi-sql-insight-editor'

async function dismissQuickStart(page: Page): Promise<void> {
    await page
        .getByRole('button', { name: 'Minimize' })
        .click({ timeout: 1000 })
        .catch(() => {})
}

async function goToSqlEditor(page: Page, path: string = '/sql'): Promise<void> {
    await page.goto(path)
    await expect(page.getByTestId('editor-scene')).toBeVisible({ timeout: 60000 })
    await expect(page.getByText('Loading...', { exact: true })).toHaveCount(0, { timeout: 60000 })
    await dismissQuickStart(page)
}

async function runQuery(page: Page, query: string): Promise<void> {
    const sqlInsight = new SqlInsight(page)
    const runButton = page.getByTestId('sql-editor-run-button')

    await sqlInsight.writeQuery(query)
    await sqlInsight.run()

    await expect(runButton).toContainText('Run', { timeout: 60000 })
}

// The insight builder is a cross-stack flow: wells compile to SQL on the frontend, the backend
// runs both the base and the compiled query, and what's saved must survive a reopen. The feature
// flag gates only *creating* builder insights (fresh tabs) — editing a saved one is content-gated:
// a builder config that still describes its SQL opens in the builder for everyone, and hand-edited
// ("stale") SQL wins and opens classic. Each of these journeys broke during development in ways no
// logic-level test could see (mount wiring, hosting decisions, save round trips).
test.describe('SQL editor insight builder', () => {
    test.describe.configure({ mode: 'serial' })
    test.setTimeout(120000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null
    let insightShortId: string | null = null
    const insightName = `Builder insight ${Date.now()}`

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            skip_onboarding: true,
            use_current_time: true,
        })
    })

    test('builds a chart from a query, inspects its views, and saves it as an insight', async ({
        page,
        playwrightSetup,
    }) => {
        await mockFeatureFlags(page, { [BUILDER_FLAG]: true })
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
        await goToSqlEditor(page)

        await test.step('Source and Visualization tabs frame the scene', async () => {
            const sceneTabs = page.getByTestId('sql-builder-scene-tabs')
            await expect(sceneTabs).toBeVisible()
            await expect(sceneTabs).toContainText('Source')
            await expect(sceneTabs).toContainText('Visualization')
        })

        await test.step('run the base query on the Source tab', async () => {
            await runQuery(page, 'SELECT 1 AS result')
            await expect(page.getByRole('columnheader', { name: /result/i })).toBeVisible()
            await expect(page.getByRole('gridcell', { name: '1' })).toBeVisible()
        })

        await test.step('Visualization replaces the editor with the builder canvas', async () => {
            await page.getByTestId('sql-builder-scene-tabs').getByText('Visualization').click()
            await expect(page.getByTestId('sql-builder-canvas')).toBeVisible()
            // The query pane stays mounted (Monaco keeps its model across tab flips) but hidden
            await expect(page.getByTestId('hogql-query-editor')).toBeHidden()
        })

        await test.step('clicking a field compiles and runs a chart', async () => {
            await page.getByRole('button', { name: 'Add result to the chart', exact: true }).click({ timeout: 60000 })
            await expect(page.getByTestId('sql-builder-status-bar')).toContainText('1 row', { timeout: 60000 })
            await expect(page.getByTestId('sql-builder-view-toggle')).toBeVisible()
        })

        await test.step('the view toggle shows the generated SQL and its results', async () => {
            const toggleButtons = page.getByTestId('sql-builder-view-toggle').getByRole('button')
            await toggleButtons.nth(2).click()
            await expect(page.getByTestId('sql-builder-generated-sql')).toContainText('sum(result)')
            await toggleButtons.nth(1).click()
            await expect(page.getByTestId('sql-builder-results-table')).toBeVisible()
            await toggleButtons.nth(0).click()
        })

        await test.step('Source keeps the base query and its raw rows', async () => {
            await page.getByTestId('sql-builder-scene-tabs').getByText('Source').click()
            await expect(page.getByTestId('hogql-query-editor')).toBeVisible()
            await expect(page.getByTestId('hogql-query-editor')).toContainText('SELECT 1 AS result')
            await expect(page.getByRole('columnheader', { name: /result/i })).toBeVisible({ timeout: 60000 })
        })

        await test.step('save as insight navigates to the insight view', async () => {
            await dismissQuickStart(page)
            await page.getByRole('button', { name: 'Save as insight', exact: true }).click()
            // LemonModal's dialog element carries no accessible name, so match on content
            const dialog = page.locator('.LemonModal').filter({ hasText: 'Save as new insight' })
            await expect(dialog).toBeVisible()
            await dialog.getByTestId('insight-name').fill(insightName)
            await dialog.getByRole('button', { name: 'Submit' }).click()
            await expect(dialog).not.toBeVisible({ timeout: 60000 })

            // The save hands the user their insight, like the classic editor
            await expect(page).toHaveURL(/\/insights\/[A-Za-z0-9]+$/, { timeout: 60000 })
            await expect(page.getByText(insightName, { exact: true }).first()).toBeVisible({ timeout: 60000 })

            insightShortId = new URL(page.url()).pathname.split('/').pop() ?? null
            expect(insightShortId).toBeTruthy()
        })

        await test.step('a hard reload straight into Visualization hydrates the chart', async () => {
            // The reload-style URL (#q=...&output_tab=visualization&insight=...) races the lazy
            // canvas chunk, the insight fetch, and feature flags — the canvas must come back
            // showing the chart, never the "pick fields" empty state
            await goToSqlEditor(page, `/sql?open_insight=${insightShortId}`)
            await expect(page.getByTestId('sql-builder-canvas')).toBeVisible({ timeout: 60000 })
            await page.reload()
            await expect(page.getByTestId('editor-scene')).toBeVisible({ timeout: 60000 })
            await dismissQuickStart(page)
            await expect(page.getByTestId('sql-builder-canvas')).toBeVisible({ timeout: 60000 })
            await expect(page.getByTestId('sql-builder-status-bar')).toContainText('1 row', { timeout: 60000 })
            await expect(page.getByText('Pick fields to chart')).toHaveCount(0)
        })
    })

    test('editing a builder insight is content-gated, not flag-gated', async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)

        await test.step('flag off: the insight still opens in the builder, base SQL in the buffer', async () => {
            await goToSqlEditor(page, `/sql?open_insight=${insightShortId}`)
            await expect(page.getByTestId('sql-builder-scene-tabs')).toBeVisible({ timeout: 60000 })
            await page.getByTestId('sql-builder-scene-tabs').getByText('Source').click()
            await expect(page.getByTestId('hogql-query-editor')).toContainText('SELECT 1 AS result', {
                timeout: 60000,
            })
        })

        await test.step('flag off: a whole-buffer run adopts the edited base', async () => {
            await runQuery(page, 'SELECT 2 AS result')
            await expect(page.getByRole('gridcell', { name: '2' })).toBeVisible({ timeout: 60000 })
        })

        await test.step('flag off: updating keeps the builder config, in lockstep with the SQL', async () => {
            await dismissQuickStart(page)
            await page.getByRole('button', { name: 'Update insight', exact: true }).click()
            await expect(page.getByText('Insight updated')).toBeVisible({ timeout: 60000 })

            // The persisted config must describe the new SQL exactly — a drifted compiledQuery
            // snapshot would demote the insight to the classic editor on its next open
            const response = await page.request.get(`/api/environments/@current/insights/?short_id=${insightShortId}`)
            expect(response.ok()).toBeTruthy()
            const { results } = await response.json()
            expect(results).toHaveLength(1)
            expect(results[0].query.builder?.baseQuery).toEqual('SELECT 2 AS result')
            expect(results[0].query.builder?.compiledQuery).toEqual(results[0].query.source.query)
        })

        await test.step('flag back on: the insight reopens in the builder with the adopted base', async () => {
            await mockFeatureFlags(page, { [BUILDER_FLAG]: true })
            await goToSqlEditor(page, `/sql?open_insight=${insightShortId}`)
            await expect(page.getByTestId('sql-builder-scene-tabs')).toBeVisible({ timeout: 60000 })
            await page.getByTestId('sql-builder-scene-tabs').getByText('Source').click()
            await expect(page.getByTestId('hogql-query-editor')).toContainText('SELECT 2 AS result', {
                timeout: 60000,
            })
        })

        await test.step('SQL hand-edited outside the builder wins: the insight opens classic', async () => {
            // Simulate an API edit that desyncs the SQL from the builder config
            const listResponse = await page.request.get(
                `/api/environments/@current/insights/?short_id=${insightShortId}`
            )
            const { results } = await listResponse.json()
            const insight = results[0]
            const patchResponse = await page.request.patch(`/api/environments/@current/insights/${insight.id}/`, {
                data: {
                    query: { ...insight.query, source: { ...insight.query.source, query: 'SELECT 3 AS result' } },
                },
            })
            expect(patchResponse.ok()).toBeTruthy()

            await goToSqlEditor(page, `/sql?open_insight=${insightShortId}`)
            await expect(page.getByTestId('hogql-query-editor')).toContainText('SELECT 3 AS result', {
                timeout: 60000,
            })
            await expect(page.getByTestId('sql-builder-scene-tabs')).toHaveCount(0)
        })
    })
})
