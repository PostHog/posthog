/**
 * Regression test: shared dashboards must render in a fully unauthenticated browser context.
 * Added after a fix that skipped "always-401" API calls in shared/exported views had to be
 * reverted — the skip broke the shared dashboard render path. A logged-out goto of
 * /shared/{token} reliably reproduces that class of regression.
 */
import { expect, Page } from '@playwright/test'

import { InsightVizNode, NodeKind, TrendsQuery } from '../../frontend/src/queries/schema/schema-general'
import { SharingConfigurationType } from '../../frontend/src/types'
import { PlaywrightSetup } from '../utils/playwright-setup'
import { test } from '../utils/workspace-test-base'

async function createSharedDashboard(
    page: Page,
    playwrightSetup: PlaywrightSetup,
    orgName: string
): Promise<{ sharingData: SharingConfigurationType; dashboardName: string; insightName: string }> {
    const workspace = await playwrightSetup.createWorkspace(orgName)
    const authHeaders = {
        Authorization: `Bearer ${workspace.personal_api_key}`,
        'Content-Type': 'application/json',
    }

    const dashboardName = 'Logged-out dashboard render'
    const dashboardResponse = await page.request.post(`/api/projects/${workspace.team_id}/dashboards/`, {
        headers: authHeaders,
        data: { name: dashboardName },
    })
    expect(dashboardResponse.ok()).toBe(true)
    const dashboardData = await dashboardResponse.json()

    const insightName = 'Trends pageview tile'
    const insightPayload: { name: string; query: InsightVizNode<TrendsQuery>; dashboards: number[] } = {
        name: insightName,
        query: {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                dateRange: { date_from: '2024-10-04', date_to: '2024-11-03', explicitDate: true },
            },
        },
        dashboards: [dashboardData.id],
    }

    const insightResponse = await page.request.post(`/api/projects/${workspace.team_id}/insights/`, {
        headers: authHeaders,
        data: insightPayload,
    })
    expect(insightResponse.ok()).toBe(true)

    const sharingResponse = await page.request.patch(
        `/api/projects/${workspace.team_id}/dashboards/${dashboardData.id}/sharing`,
        {
            headers: authHeaders,
            data: { enabled: true },
        }
    )
    expect(sharingResponse.ok()).toBe(true)
    const sharingData: SharingConfigurationType = await sharingResponse.json()
    expect(sharingData.access_token).toBeTruthy()
    expect(sharingData.enabled).toBe(true)

    return { sharingData, dashboardName, insightName }
}

test.describe('Shared dashboard (unauthenticated)', () => {
    test('renders successfully in a logged-out browser context', async ({ browser, page, playwrightSetup }) => {
        const { sharingData, dashboardName, insightName } = await createSharedDashboard(
            page,
            playwrightSetup,
            'Unauth Shared Dashboard Test Org'
        )

        const unauthContext = await browser.newContext({ storageState: { cookies: [], origins: [] } })
        const unauthPage = await unauthContext.newPage()

        try {
            await unauthPage.goto(`/shared/${sharingData.access_token}`)

            await expect(unauthPage.locator('body.ExporterBody')).toBeVisible()
            await expect(unauthPage.locator(`text=${dashboardName}`)).toBeVisible({ timeout: 30000 })
            await expect(unauthPage.locator(`text=${insightName}`)).toBeVisible({ timeout: 30000 })
            await expect(unauthPage.locator('[data-attr="insights-graph"]').first()).toBeVisible({ timeout: 30000 })
        } finally {
            await unauthContext.close()
        }
    })
})
