import { NodeKind } from '../../../../frontend/src/queries/schema/schema-general'
import { InsightPage } from '../../../page-models/insightPage'
import { randomString } from '../../../utils'
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

    test('Duplicate insight from side panel', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create and save insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Side Panel Duplicate Test')
            await insight.save()
        })

        await test.step('open side panel and click duplicate', async () => {
            await insight.openInfoPanel()
            const duplicateButton = page.getByTestId('insight-duplicate-button')
            await expect(duplicateButton).toBeVisible()
            await duplicateButton.click()
        })

        await test.step('navigated to new insight in edit mode with (copy) name', async () => {
            await page.waitForURL(/\/edit/)
            await expect(insight.topBarName).toContainText('Side Panel Duplicate Test (copy)')
        })
    })

    test('Favorite insight from side panel shows in favorites list', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightName = randomString('Favorite Test')

        await test.step('create and save insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await insight.trends.waitForChart()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('open side panel and click favorite', async () => {
            await insight.openInfoPanel()
            const favoriteButton = page.getByTestId('insight-favorite-button')
            // After saving a new insight the URL changes and insightLogic remounts,
            // which triggers a GET to load the insight. Until that completes,
            // short_id is null and the button is disabled. Waiting for enabled
            // ensures the insight is fully loaded so the click triggers the PATCH.
            await expect(favoriteButton).toBeEnabled()

            const responsePromise = page.waitForResponse(
                (resp) => resp.url().includes('/api/environments/') && resp.request().method() === 'PATCH'
            )
            await favoriteButton.click()
            await responsePromise
            await expect(favoriteButton).toHaveAttribute('data-active', 'true')
        })

        await test.step('insight appears in favorites list on product analytics page', async () => {
            await page.goto('/insights')
            await page.getByRole('button', { name: 'Favorites' }).click()
            await expect(page.getByText(insightName)).toBeVisible()
        })
    })

    test('View source toggle enters edit mode and shows query editor', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create and save insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Side Panel Source Test')
            await insight.save()
            await insight.trends.waitForChart()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('open side panel and click view source', async () => {
            await insight.openInfoPanel()
            const viewSourceSwitch = page.getByTestId('insight-show-source')
            await expect(viewSourceSwitch).toBeVisible()
            await viewSourceSwitch.click()
        })

        await test.step('enters edit mode and shows query editor', async () => {
            await expect(insight.saveButton).toBeVisible()
            await expect(page.getByTestId('query-editor')).toBeVisible()
        })
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

    test('Export insight as Terraform and download the file', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('navigate to seeded insight', async () => {
            await page.goto(insightUrl)
        })

        await test.step('open terraform modal and wait for HCL to load', async () => {
            await insight.openInfoPanel()
            await page.getByTestId('insight-manage-terraform').click()
            const modal = page.getByTestId('insight-terraform-modal')
            await expect(modal).toBeVisible()
            await expect(modal.getByText('resource "posthog_')).toBeVisible({ timeout: 10_000 })
        })

        await test.step('click download and verify the .tf file', async () => {
            const modal = page.getByTestId('insight-terraform-modal')
            const downloadPromise = page.waitForEvent('download')
            await modal.getByRole('button', { name: /Download.*\.tf/ }).click()
            const download = await downloadPromise
            expect(download.suggestedFilename()).toMatch(/\.tf$/)
        })
    })
})
