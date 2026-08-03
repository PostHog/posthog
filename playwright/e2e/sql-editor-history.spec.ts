import { Page } from '@playwright/test'

import { NodeKind } from '../../frontend/src/queries/schema/schema-general'
import { InsightShortId } from '../../frontend/src/types'
import { InsightPage } from '../page-models/insightPage'
import { expect, test, PlaywrightWorkspaceSetupResult } from '../utils/workspace-test-base'

async function expectSaveOptions(page: Page, expectedOption: string): Promise<void> {
    const saveOption = page.getByRole('menuitem', { name: expectedOption, exact: true })

    await expect(async () => {
        await page.keyboard.press('Escape')
        await page.getByTestId('sql-editor-save-options-button').click()
        await expect(saveOption).toBeVisible({ timeout: 5_000 })
    }).toPass({ timeout: 30_000 })
    await page.keyboard.press('Escape')
}

test.describe('SQL editor history', () => {
    test.setTimeout(120_000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            insights: [
                {
                    name: 'Seeded SQL insight',
                    query: {
                        kind: NodeKind.DataVisualizationNode,
                        source: {
                            kind: NodeKind.HogQLQuery,
                            query: 'SELECT event, count() FROM events GROUP BY event ORDER BY count() DESC LIMIT 5',
                        },
                        chartSettings: {},
                        tableSettings: {},
                    },
                },
            ],
        })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('preserves saved insight editing state across browser back and forward', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightShortId = workspace!.created_insights![0].short_id as InsightShortId

        await test.step('open a saved SQL insight in the SQL editor', async () => {
            await insight.goToInsight(insightShortId, { edit: true })
            await page.waitForURL(/\/sql/)
            await expectSaveOptions(page, 'Update insight')
        })

        await test.step('navigating to a plain SQL query in the same editor switches to save-as-new mode', async () => {
            await page.evaluate(() => {
                const url = new URL(window.location.href)
                url.search = ''
                url.hash = new URLSearchParams({ q: 'SELECT 1' }).toString()
                window.history.pushState({}, '', url.toString())
                window.dispatchEvent(new PopStateEvent('popstate'))
            })

            await expectSaveOptions(page, 'Save as insight')
        })

        await test.step('browser back restores the saved SQL insight editor state', async () => {
            await page.goBack()
            await page.waitForURL(/insight=/)
            await expectSaveOptions(page, 'Update insight')
        })

        await test.step('browser forward restores the plain SQL query state', async () => {
            await page.goForward()
            await page.waitForURL((url) => url.hash.includes('q=SELECT%201') && !url.hash.includes('insight='))
            await expectSaveOptions(page, 'Save as insight')
        })
    })
})
