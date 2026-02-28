import { InsightPage } from '../../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../../utils/workspace-test-base'

test.describe('Insight side panel actions', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
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

        await test.step('create and save insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Side Panel Favorite Test')
            await insight.save()
            await insight.trends.waitForChart()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('open side panel and click favorite', async () => {
            await insight.openInfoPanel()
            const favoriteButton = page.getByTestId('insight-favorite-button')
            await expect(favoriteButton).toBeVisible()
            await favoriteButton.click()
        })

        await test.step('insight appears in favorites list on product analytics page', async () => {
            await page.goto('/insights')
            await page.getByRole('button', { name: 'Favorites' }).click()
            await expect(page.getByText('Side Panel Favorite Test')).toBeVisible()
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
})
