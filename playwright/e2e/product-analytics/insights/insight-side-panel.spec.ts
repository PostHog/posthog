import { NodeKind } from '../../../../frontend/src/queries/schema/schema-general'
import { InsightPage } from '../../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

test.describe('Insight side panel actions', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null
    let insightUrl: string

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({
            use_current_time: true,
            skip_onboarding: true,
            insights: [
                {
                    name: 'Side Panel Test Insight',
                    query: {
                        kind: NodeKind.InsightVizNode,
                        source: {
                            kind: NodeKind.TrendsQuery,
                            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                        },
                    },
                },
            ],
        })
        const shortId = workspace!.created_insights![0].short_id
        insightUrl = `/project/${workspace!.team_id}/insights/${shortId}`
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Open sharing modal from side panel', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to seeded insight', async () => {
            await page.goto(insightUrl)
        })

        await test.step('click share and verify sharing modal opens', async () => {
            await insight.openInfoPanel()
            await page.getByTestId('insight-share-button').click()
            const modal = page.getByTestId('insight-sharing-modal')
            await expect(modal).toBeVisible()
            await expect(modal.getByTestId('sharing-switch')).toBeVisible()
        })

        await test.step('toggle sharing on and verify share link appears', async () => {
            const modal = page.getByTestId('insight-sharing-modal')
            await modal.getByTestId('sharing-switch').click()
            await expect(modal.getByTestId('sharing-link-button')).toBeVisible()
        })
    })

    test('Open subscriptions modal from side panel', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to seeded insight', async () => {
            await page.goto(insightUrl)
        })

        await test.step('click subscribe and verify subscriptions modal opens', async () => {
            await insight.openInfoPanel()
            await page.getByTestId('insight-subscribe-dropdown-menu-item').click()
            const modal = page.getByTestId('insight-subscriptions-modal')
            await expect(modal).toBeVisible()
        })
    })
})
