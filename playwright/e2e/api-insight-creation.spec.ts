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
    const workspace = await playwrightSetup.createWorkspace({
        organization_name: 'API Test Org',
        skip_onboarding: true,
    })

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

    // Login and navigate directly to the insight page
    await playwrightSetup.login(page, workspace)
    await page.goto(`/project/${workspace.team_id}/insights/${insightData.short_id}`)

    // Wait for the insight query to finish loading
    await page.getByTestId('insight-loading-waiting-message').waitFor({ state: 'detached', timeout: 30000 })

    // Wait for the insights graph container to be visible and loaded
    await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible({ timeout: 30000 })

    // Verify the insight rendered — either a chart canvas or an empty state
    const canvas = page.locator('[data-attr="insights-graph"] canvas')
    const emptyState = page.getByText('There are no matching events for this query')
    await expect(canvas.or(emptyState)).toBeVisible({ timeout: 30000 })

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
