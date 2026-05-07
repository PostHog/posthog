/**
 * Regression test: shared notebooks must render in a fully unauthenticated browser context.
 * Sibling to shared-dashboard-unauthenticated.spec.ts — ensures the ExporterNotebookScene
 * code path keeps working when the exporter bundle / shared-view skipping evolves.
 */
import { expect, Page } from '@playwright/test'

import { SharingConfigurationType } from '../../frontend/src/types'
import { PlaywrightSetup } from '../utils/playwright-setup'
import { test } from '../utils/workspace-test-base'

async function createSharedNotebook(
    page: Page,
    playwrightSetup: PlaywrightSetup,
    orgName: string
): Promise<{ sharingData: SharingConfigurationType; notebookTitle: string; paragraphText: string }> {
    const workspace = await playwrightSetup.createWorkspace(orgName)
    const authHeaders = {
        Authorization: `Bearer ${workspace.personal_api_key}`,
        'Content-Type': 'application/json',
    }

    const notebookTitle = 'Logged-out notebook render'
    const paragraphText = 'Anonymous notebook body content'
    const notebookContent = {
        type: 'doc',
        content: [
            {
                type: 'heading',
                attrs: { level: 1 },
                content: [{ type: 'text', text: notebookTitle }],
            },
            {
                type: 'paragraph',
                content: [{ type: 'text', text: paragraphText }],
            },
        ],
    }

    const notebookResponse = await page.request.post(`/api/projects/${workspace.team_id}/notebooks/`, {
        headers: authHeaders,
        data: { title: notebookTitle, content: notebookContent },
    })
    expect(notebookResponse.ok()).toBe(true)
    const notebookData = await notebookResponse.json()
    expect(notebookData.short_id).toBeTruthy()

    const sharingResponse = await page.request.patch(
        `/api/projects/${workspace.team_id}/notebooks/${notebookData.short_id}/sharing/`,
        {
            headers: authHeaders,
            data: { enabled: true },
        }
    )
    expect(sharingResponse.ok()).toBe(true)
    const sharingData: SharingConfigurationType = await sharingResponse.json()
    expect(sharingData.access_token).toBeTruthy()
    expect(sharingData.enabled).toBe(true)

    return { sharingData, notebookTitle, paragraphText }
}

test.describe('Shared notebook (unauthenticated)', () => {
    test('renders successfully in a logged-out browser context', async ({ browser, page, playwrightSetup }) => {
        const { sharingData, notebookTitle, paragraphText } = await createSharedNotebook(
            page,
            playwrightSetup,
            'Unauth Shared Notebook Test Org'
        )

        const unauthContext = await browser.newContext({ storageState: { cookies: [], origins: [] } })
        const unauthPage = await unauthContext.newPage()

        try {
            await unauthPage.goto(`/shared/${sharingData.access_token}`)

            await expect(unauthPage.locator('body.ExporterBody')).toBeVisible()
            await expect(unauthPage.locator(`text=${notebookTitle}`).first()).toBeVisible({ timeout: 30000 })
            await expect(unauthPage.locator(`text=${paragraphText}`)).toBeVisible({ timeout: 30000 })
        } finally {
            await unauthContext.close()
        }
    })
})
