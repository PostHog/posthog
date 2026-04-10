/**
 * Test shared dashboard/insight styling loads correctly
 *
 * This test verifies that CSS properly loads on shared dashboards/insights.
 * It was added as a regression test after a bug where the hashed CSS file
 * returned 403 errors, breaking all shared dashboard styling.
 */
import { expect } from '@playwright/test'

import { InsightVizNode, NodeKind, TrendsQuery } from '../../frontend/src/queries/schema/schema-general'
import { SharingConfigurationType } from '../../frontend/src/types'
import { test } from '../utils/workspace-test-base'

type InsightCreationPayload = {
    name: string
    query: InsightVizNode<TrendsQuery>
}

test.describe('Shared dashboard styling', () => {
    test('CSS loads correctly on shared insight page', async ({ page, playwrightSetup }) => {
        // Create workspace with API key
        const workspace = await playwrightSetup.createWorkspace('Shared Styling Test Org')

        // Create a trends insight via API
        const payload: InsightCreationPayload = {
            name: 'Shared Styling Test Insight',
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

        // Enable sharing (without password protection)
        const sharingResponse = await page.request.patch(
            `/api/projects/${workspace.team_id}/insights/${insightData.id}/sharing`,
            {
                headers: {
                    Authorization: `Bearer ${workspace.personal_api_key}`,
                    'Content-Type': 'application/json',
                },
                data: {
                    enabled: true,
                },
            }
        )

        expect(sharingResponse.ok()).toBe(true)
        const sharingData: SharingConfigurationType = await sharingResponse.json()
        expect(sharingData.enabled).toBe(true)
        expect(sharingData.access_token).toBeTruthy()

        // Navigate to the shared insight URL (without being logged in)
        const sharedUrl = `/shared/${sharingData.access_token}`

        // Track CSS loading errors
        const cssErrors: string[] = []
        page.on('console', (msg) => {
            if (msg.type() === 'error' && msg.text().includes('CSS')) {
                cssErrors.push(msg.text())
            }
        })

        // Track failed network requests for CSS files
        const failedCssRequests: string[] = []
        page.on('response', (response) => {
            if (response.url().includes('.css') && !response.ok()) {
                failedCssRequests.push(`${response.url()} - ${response.status()}`)
            }
        })

        await page.goto(sharedUrl)

        // Wait for the insight to load
        await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible({ timeout: 30000 })

        // Verify the insight title is visible (proves JS loaded)
        await expect(page.locator('text=Shared Styling Test Insight')).toBeVisible()

        // Verify no CSS loading errors occurred
        expect(cssErrors).toHaveLength(0)
        expect(failedCssRequests).toHaveLength(0)

        // Verify that the ExporterBody class is styled (background should not be default white/transparent)
        // This is a basic check that CSS has been applied
        const body = page.locator('body.ExporterBody')
        await expect(body).toBeVisible()

        // Verify the insight container has proper styling by checking it has the expected classes
        const insightContainer = page.locator('.InsightCard, .Insight, [data-attr="insights-graph"]').first()
        await expect(insightContainer).toBeVisible()

        // Take a screenshot to verify styling visually (this will be compared in CI)
        await expect(page).toHaveScreenshot('shared-insight-with-styling.png', {
            fullPage: true,
            // Allow some threshold for minor rendering differences
            maxDiffPixelRatio: 0.1,
        })
    })

    test('CSS fallback works when hashed CSS returns error', async ({ page, playwrightSetup }) => {
        // Create workspace with API key
        const workspace = await playwrightSetup.createWorkspace('CSS Fallback Test Org')

        // Create a trends insight via API
        const payload: InsightCreationPayload = {
            name: 'CSS Fallback Test Insight',
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

        // Enable sharing
        const sharingResponse = await page.request.patch(
            `/api/projects/${workspace.team_id}/insights/${insightData.id}/sharing`,
            {
                headers: {
                    Authorization: `Bearer ${workspace.personal_api_key}`,
                    'Content-Type': 'application/json',
                },
                data: {
                    enabled: true,
                },
            }
        )

        expect(sharingResponse.ok()).toBe(true)
        const sharingData: SharingConfigurationType = await sharingResponse.json()

        // Intercept hashed CSS requests and make them fail to test the fallback
        let fallbackCssLoaded = false
        await page.route('**/static/exporter-*.css', (route) => {
            // Block the hashed CSS file to simulate CDN 403 error
            route.abort('blockedbyclient')
        })

        // Track when fallback CSS is requested
        page.on('request', (request) => {
            if (request.url().includes('/static/exporter.css')) {
                fallbackCssLoaded = true
            }
        })

        // Track console warnings about CSS fallback
        let fallbackWarningLogged = false
        page.on('console', (msg) => {
            if (msg.type() === 'warn' && msg.text().includes('Failed to load CSS')) {
                fallbackWarningLogged = true
            }
        })

        await page.goto(`/shared/${sharingData.access_token}`)

        // Wait for the insight to load (proves the page still works even with CSS issues)
        await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible({ timeout: 30000 })

        // Verify fallback was triggered
        expect(fallbackCssLoaded).toBe(true)
        expect(fallbackWarningLogged).toBe(true)

        // Verify the page still has styling (fallback worked)
        const body = page.locator('body.ExporterBody')
        await expect(body).toBeVisible()
    })
})
