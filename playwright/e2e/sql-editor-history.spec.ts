import { NodeKind } from '../../frontend/src/queries/schema/schema-general'
import { InsightShortId } from '../../frontend/src/types'
import { InsightPage } from '../page-models/insightPage'
import { expect, test, PlaywrightWorkspaceSetupResult } from '../utils/workspace-test-base'

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
            await expect(page.getByRole('button', { name: 'Update insight' })).toBeVisible({ timeout: 30000 })
        })

        await test.step('navigating to a plain SQL query in the same editor switches to save-as-new mode', async () => {
            await page.evaluate(() => {
                const url = new URL(window.location.href)
                url.search = ''
                url.hash = new URLSearchParams({ q: 'SELECT 1' }).toString()
                window.history.pushState({}, '', url.toString())
                window.dispatchEvent(new PopStateEvent('popstate'))
            })

            await expect(page.getByRole('button', { name: 'Save as insight' })).toBeVisible()
            await expect(page.getByRole('button', { name: 'Update insight' })).toHaveCount(0)
        })

        await test.step('browser back restores the saved SQL insight editor state', async () => {
            await page.goBack()
            await page.waitForURL(/insight=/)
            await expect(page.getByRole('button', { name: 'Update insight' })).toBeVisible({ timeout: 30000 })
        })

        await test.step('browser forward restores the plain SQL query state', async () => {
            await page.goForward()
            await page.waitForURL((url) => url.hash.includes('q=SELECT%201') && !url.hash.includes('insight='))
            await expect(page.getByRole('button', { name: 'Save as insight' })).toBeVisible()
            await expect(page.getByRole('button', { name: 'Update insight' })).toHaveCount(0)
        })
    })
})
