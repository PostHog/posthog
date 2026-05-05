import { Page } from '@playwright/test'

import { NodeKind } from '../../frontend/src/queries/schema/schema-general'
import { ChartDisplayType, InsightShortId } from '../../frontend/src/types'
import { expect, test, PlaywrightWorkspaceSetupResult } from '../utils/workspace-test-base'

async function goToSavedSqlInsight(page: Page, insightShortId: InsightShortId): Promise<void> {
    await page.goto(`/sql#insight=${insightShortId}`, { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/sql#.*insight=/)
    await expect(page.getByRole('button', { name: 'Update insight' })).toBeVisible({ timeout: 30_000 })
    await expect(page.locator('.DataVisualization canvas').last()).toBeVisible({ timeout: 60_000 })
}

test.describe('SQL editor axis labels', () => {
    test.setTimeout(120_000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            insights: [
                {
                    name: 'Axis labels SQL chart',
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: 'SELECT event, count() AS events, uniq(distinct_id) AS people FROM events GROUP BY event ORDER BY events DESC LIMIT 5',
                        },
                        display: ChartDisplayType.ActionsBar,
                        chartSettings: {
                            xAxis: {
                                column: 'event',
                            },
                            yAxis: [
                                {
                                    column: 'events',
                                    settings: {
                                        display: {
                                            yAxisPosition: 'left',
                                        },
                                    },
                                },
                                {
                                    column: 'people',
                                    settings: {
                                        display: {
                                            yAxisPosition: 'right',
                                        },
                                    },
                                },
                            ],
                        },
                        tableSettings: {},
                    },
                },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('adds axis labels to a saved SQL chart and persists them', async ({ page }) => {
        const insightShortId = workspace!.created_insights![0].short_id as InsightShortId

        await goToSavedSqlInsight(page, insightShortId)

        await page.getByTestId('sql-editor-visualization-settings-button').click()
        await page.getByRole('tab', { name: 'Display' }).click()

        await page.getByTestId('data-visualization-x-axis-label-input').fill('Event name')
        await page.getByText('Left Y-axis').click()
        await page.getByTestId('data-visualization-left-y-axis-label-input').fill('Events')
        await page.getByText('Right Y-axis').click()
        await page.getByTestId('data-visualization-right-y-axis-label-input').fill('People')

        const saveRequestPromise = page.waitForResponse(
            (response) =>
                /\/api\/(?:projects|environments)\/\d+\/insights(?:\/\d+)?\/?(?:\?.*)?$/.test(response.url()) &&
                response.request().method() === 'PATCH',
            { timeout: 60_000 }
        )

        await page.getByRole('button', { name: 'Update insight' }).click()
        await expect((await saveRequestPromise).ok()).toBe(true)

        await goToSavedSqlInsight(page, insightShortId)

        await page.getByTestId('sql-editor-visualization-settings-button').click()
        await page.getByRole('tab', { name: 'Display' }).click()

        await expect(page.getByTestId('data-visualization-x-axis-label-input')).toHaveValue('Event name')
        await page.getByText('Left Y-axis').click()
        await expect(page.getByTestId('data-visualization-left-y-axis-label-input')).toHaveValue('Events')
        await page.getByText('Right Y-axis').click()
        await expect(page.getByTestId('data-visualization-right-y-axis-label-input')).toHaveValue('People')
    })
})
