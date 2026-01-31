import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Save Advanced', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('cancel insight creation without saving', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight and make changes', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Unsaved Insight')
        })

        await test.step('navigate back to insights list without saving', async () => {
            await insight.goToList()
        })

        await test.step('verify the unsaved insight does not appear in the list', async () => {
            await expect(page.locator('table')).toBeVisible()
            await expect(page.getByText('Unsaved Insight')).not.toBeVisible()
        })
    })

    test('save insight and verify all configurations persist', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight with complex config', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Complex Insight')
            await insight.trends.addSeries()
            await insight.trends.addBreakdown('Browser')
            await insight.trends.waitForChart()
        })

        await test.step('save the insight', async () => {
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('reload and verify all configurations persist', async () => {
            await page.reload({ waitUntil: 'networkidle' })
            await expect(insight.topBarName).toContainText('Complex Insight')
            await expect(insight.trends.chart).toBeVisible()
        })
    })

    test('use Save as new', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create and save an insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName('Original Insight')
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('edit the insight and add a second series', async () => {
            await insight.edit()
            await insight.trends.addSeries()
            await insight.trends.waitForChart()
        })

        await test.step('use Save as new insight option', async () => {
            const originalUrl = page.url()
            // Click the dropdown arrow next to the Save button
            await page.locator('[data-attr="insight-save-dropdown"]').click()
            await page.locator('[data-attr="insight-save-as-new-insight"]').click()
            // A modal appears asking for the new name
            const nameInput = page.getByPlaceholder('Please enter the new name')
            await nameInput.waitFor({ state: 'visible' })
            await nameInput.fill('Copied Insight')
            await page.getByRole('button', { name: 'Submit' }).click()
            await page.waitForURL((url) => url.toString() !== originalUrl, { timeout: 15000 })
        })

        await test.step('verify the new insight was created', async () => {
            await expect(insight.topBarName).toContainText('Copied Insight')
        })
    })
})
