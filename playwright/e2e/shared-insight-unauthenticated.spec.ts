/**
 * Regression test: shared insights must render in a fully unauthenticated browser context.
 * Sibling to shared-dashboard-unauthenticated.spec.ts and shared-notebook-unauthenticated.spec.ts —
 * covers the ExporterInsightScene path directly so a regression in insight sharing isn't
 * masked behind dashboard tile rendering.
 */
import { expect, Page } from '@playwright/test'

import { InsightVizNode, NodeKind, TrendsQuery } from '../../frontend/src/queries/schema/schema-general'
import { SharingConfigurationType } from '../../frontend/src/types'
import { PlaywrightSetup } from '../utils/playwright-setup'
import { expectNoTeamScopedApiLeaks, openUnauthenticatedSharedPage } from '../utils/sharedViewExpectations'
import { test } from '../utils/workspace-test-base'

async function createSharedInsight(
    page: Page,
    playwrightSetup: PlaywrightSetup,
    orgName: string
): Promise<{ sharingData: SharingConfigurationType; insightName: string }> {
    const workspace = await playwrightSetup.createWorkspace(orgName)
    const authHeaders = {
        Authorization: `Bearer ${workspace.personal_api_key}`,
        'Content-Type': 'application/json',
    }

    const insightName = 'Logged-out insight render'
    const insightPayload: { name: string; query: InsightVizNode<TrendsQuery> } = {
        name: insightName,
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
        headers: authHeaders,
        data: insightPayload,
    })
    expect(insightResponse.ok()).toBe(true)
    const insightData = await insightResponse.json()

    const sharingResponse = await page.request.patch(
        `/api/projects/${workspace.team_id}/insights/${insightData.id}/sharing`,
        {
            headers: authHeaders,
            data: { enabled: true },
        }
    )
    expect(sharingResponse.ok()).toBe(true)
    const sharingData: SharingConfigurationType = await sharingResponse.json()
    expect(sharingData.access_token).toBeTruthy()
    expect(sharingData.enabled).toBe(true)

    return { sharingData, insightName }
}

test.describe('Shared insight (unauthenticated)', () => {
    test('renders successfully in a logged-out browser context', async ({ browser, page, playwrightSetup }) => {
        const { sharingData, insightName } = await createSharedInsight(
            page,
            playwrightSetup,
            'Unauth Shared Insight Test Org'
        )

        const unauthContext = await browser.newContext({ storageState: { cookies: [], origins: [] } })
        const { unauthPage, failedApiResponses } = await openUnauthenticatedSharedPage(unauthContext)

        try {
            await unauthPage.goto(`/shared/${sharingData.access_token}`)

            await expect(unauthPage.locator('body.ExporterBody')).toBeVisible()
            await expect(unauthPage.locator(`text=${insightName}`)).toBeVisible({ timeout: 30000 })
            await expect(unauthPage.locator('[data-attr="insights-graph"]')).toBeVisible({ timeout: 30000 })

            expectNoTeamScopedApiLeaks(failedApiResponses)
        } finally {
            await unauthContext.close()
        }
    })
})
