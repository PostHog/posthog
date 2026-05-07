/**
 * Regression test: shared dashboard/insight CSS loading and fallback.
 * Added after hashed CSS files returned 403, breaking all shared dashboard styling.
 */
import { expect, Page } from '@playwright/test'

import { InsightVizNode, NodeKind, TrendsQuery } from '../../frontend/src/queries/schema/schema-general'
import { SharingConfigurationType } from '../../frontend/src/types'
import { PlaywrightSetup } from '../utils/playwright-setup'
import { test } from '../utils/workspace-test-base'

async function createSharedInsight(
    page: Page,
    playwrightSetup: PlaywrightSetup,
    orgName: string
): Promise<{ sharingData: SharingConfigurationType }> {
    const workspace = await playwrightSetup.createWorkspace(orgName)

    const payload: { name: string; query: InsightVizNode<TrendsQuery> } = {
        name: 'Shared Styling Test Insight',
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                dateRange: { date_from: '2024-10-04', date_to: '2024-11-03', explicitDate: true },
            },
        },
    }

    const insightResponse = await page.request.post(`/api/projects/${workspace.team_id}/insights/`, {
        headers: { Authorization: `Bearer ${workspace.personal_api_key}`, 'Content-Type': 'application/json' },
        data: payload,
    })
    expect(insightResponse.ok()).toBe(true)
    const insightData = await insightResponse.json()

    const sharingResponse = await page.request.patch(
        `/api/projects/${workspace.team_id}/insights/${insightData.id}/sharing`,
        {
            headers: { Authorization: `Bearer ${workspace.personal_api_key}`, 'Content-Type': 'application/json' },
            data: { enabled: true },
        }
    )
    expect(sharingResponse.ok()).toBe(true)
    const sharingData: SharingConfigurationType = await sharingResponse.json()
    expect(sharingData.access_token).toBeTruthy()

    return { sharingData }
}

test.describe('Shared dashboard styling', () => {
    test('CSS loads correctly on shared insight page', async ({ page, playwrightSetup }) => {
        const { sharingData } = await createSharedInsight(page, playwrightSetup, 'Shared Styling Test Org')

        const failedCssRequests: string[] = []
        page.on('response', (response) => {
            if (response.url().includes('.css') && !response.ok()) {
                failedCssRequests.push(`${response.url()} - ${response.status()}`)
            }
        })

        await page.goto(`/shared/${sharingData.access_token}`)
        await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible({ timeout: 30000 })
        await expect(page.locator('text=Shared Styling Test Insight')).toBeVisible()

        expect(failedCssRequests).toHaveLength(0)
        await expect(page.locator('body.ExporterBody')).toBeVisible()
    })

    test('CSS fallback works when hashed CSS returns error', async ({ page, playwrightSetup }) => {
        const { sharingData } = await createSharedInsight(page, playwrightSetup, 'CSS Fallback Test Org')

        let fallbackCssLoaded = false
        await page.route('**/static/exporter-*.css', (route) => route.abort('blockedbyclient'))
        page.on('request', (request) => {
            if (request.url().includes('/static/exporter.css')) {
                fallbackCssLoaded = true
            }
        })

        let fallbackWarningLogged = false
        page.on('console', (msg) => {
            if (msg.type() === 'warning' && msg.text().includes('Failed to load stylesheet')) {
                fallbackWarningLogged = true
            }
        })

        await page.goto(`/shared/${sharingData.access_token}`)
        await expect(page.locator('[data-attr="insights-graph"]')).toBeVisible({ timeout: 30000 })

        expect(fallbackCssLoaded).toBe(true)
        expect(fallbackWarningLogged).toBe(true)
        await expect(page.locator('body.ExporterBody')).toBeVisible()
    })
})
