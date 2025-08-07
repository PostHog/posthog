/**
 * Test creating insights via API and then viewing them in the UI
 */

import { expect } from '@playwright/test'
import { test } from '../utils/workspace-test-base'
import { InsightVizNode, TrendsQuery, NodeKind } from '../../frontend/src/queries/schema/schema-general'

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
                    date_from: '-30d',
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

    // Wait for the line graph with canvas to be visible and loaded
    await expect(page.locator('[data-attr="trend-line-graph"] canvas')).toBeVisible()

    // Now verify the insight title is correct (use more specific selector)
    await expect(page.locator('[data-attr="top-bar-name"] .EditableField__display')).toHaveText(
        'Pageview Trends Analysis'
    )

    // Take a screenshot of the insight for visual regression testing
    await page.locator('[data-attr="insights-graph"]').screenshot({
        path: '__snapshots__/pageview-trends-insight.png',
    })
})
