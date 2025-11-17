/**
 * Test creating insights via API and then viewing them in the UI
 */
import { expect } from '@playwright/test'

import { InsightVizNode, NodeKind, TrendsQuery } from '../../frontend/src/queries/schema/schema-general'
import { test } from '../utils/workspace-test-base'

type InsightCreationPayload = {
    name: string
    query: InsightVizNode<TrendsQuery>
}

test('create trends insight via API and snapshot', async ({ page, playwrightSetup }) => {
    // Create workspace with API key
    const workspace = await playwrightSetup.createWorkspace('API Test Org')

    // Create a trends insight via API using the personal API key
    const payload: InsightCreationPayload = {
        name: 'Pageview Trends Analysis',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [
                    {
                        kind: NodeKind.EventsNode,
                        event: '$pageview',
                    },
                ],
                dateRange: {
                    date_from: '2024-10-04',
                    date_to: '2024-11-03',
                    explicitDate: true,
                },
            },
        },
    }

    const insightResponse = await page.request.post(`/api/projects/${workspace.team_id}/insights/`, {
        headers: {
            Authorization: `Bearer ${workspace.personal_api_key}`,
            'Content-Type': 'application/json',
        },
        data: payload,
    })

    expect(insightResponse.ok()).toBe(true)
    const insightData = await insightResponse.json()
    expect(insightData.short_id).toBeTruthy()
    expect(insightData.name).toBe('Pageview Trends Analysis')
    expect(insightData.query.source.series[0].event).toBe('$pageview')

    // Login and navigate to the insight page using the short URL
    await playwrightSetup.loginAndNavigateToTeam(page, workspace)
    await page.goto(`/project/${workspace.team_id}/insights/${insightData.short_id}`)

    // Wait for the insights graph container to be visible and loaded
    await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible()

    // Wait for any canvas element within the insights graph (more robust than specific chart type)
    await expect(page.locator('[data-attr="insights-graph"] canvas')).toBeVisible()

    // Verify we're on the correct insight page by checking the URL
    await expect(page).toHaveURL(new RegExp(`/insights/${insightData.short_id}`))

    // Verify the insight title - check the scene name container (handles both editable and non-editable cases)
    await expect(page.locator('.scene-name')).toContainText('Pageview Trends Analysis')

    // :FIXME: Temporarily disabled due to flakiness with alerts for erroring requests
    // // Take a screenshot of the insight for visual regression testing
    // await expect(page).toHaveScreenshot('pageview-trends-insight.png', {
    //     fullPage: true,
    // })
})
