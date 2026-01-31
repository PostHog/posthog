import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Save and Persistence', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('save a Trends insight with description', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('set name and description', async () => {
            await insight.editName('User Signups')
            const descriptionField = page.getByTestId('scene-description-textarea')
            await descriptionField.click()
            await descriptionField.fill('Tracking daily user signups')
            // Blur to trigger saveOnBlur
            await descriptionField.blur()
        })

        await test.step('save the insight', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
            expect(page.url()).not.toContain('/new')
        })

        await test.step('reload and verify name and description persist', async () => {
            await page.reload({ waitUntil: 'networkidle' })
            await expect(insight.topBarName).toContainText('User Signups')
            await expect(page.getByText('Tracking daily user signups')).toBeVisible()
        })
    })

    test('edit a saved insight and update', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create and save a Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Download Activity')
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('edit and add a second series', async () => {
            await insight.edit()
            await insight.trends.addSeries()
            await insight.trends.waitForChart()
        })

        await test.step('save the updated insight', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('reload and verify the change persisted', async () => {
            await page.reload({ waitUntil: 'networkidle' })
            await insight.trends.waitForChart()
            // In view mode, click Edit to see series rows
            await insight.edit()
            await expect(insight.trends.secondSeries).toBeVisible()
        })
    })
})
