/**
 * Test creating insights via API and then viewing them in the UI
 */

import { expect } from '@playwright/test'
import { test } from '../utils/enhanced-test-base'

test('create trends insight via API and snapshot', async ({ page, playwrightSetup }) => {
    // Create workspace with API key
    const workspace = await playwrightSetup.createWorkspace('API Test Org', 'Analytics Project')

    // Create a trends insight via API using the personal API key
    const insightResponse = await page.request.post(`/api/projects/${workspace.teamId}/insights/`, {
        headers: {
            Authorization: `Bearer ${workspace.personalApiKey}`,
            'Content-Type': 'application/json',
        },
        data: {
            name: 'Pageview Trends Analysis',
            filters: {
                events: [{ id: '$pageview' }],
                insight: 'TRENDS',
                date_from: '-30d',
            },
        },
    })

    expect(insightResponse.ok()).toBe(true)
    const insightData = await insightResponse.json()
    expect(insightData.short_id).toBeTruthy()
    expect(insightData.name).toBe('Pageview Trends Analysis')
    expect(insightData.filters.events[0].id).toBe('$pageview')

    // Login and navigate to the insight page using the short URL
    await playwrightSetup.loginAndNavigateToTeam(page, workspace.teamId)
    await page.goto(`/project/${workspace.teamId}/insights/${insightData.short_id}`)

    // Wait for the insight to load
    await expect(page.locator('[data-attr="insight-name"]')).toHaveText('Pageview Trends Analysis')

    // Wait for the chart to be visible and loaded
    await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible()

    // Take a screenshot of the insight
    await expect(page.locator('[data-attr="insights-graph"]')).toHaveScreenshot('pageview-trends-insight.png')
})
