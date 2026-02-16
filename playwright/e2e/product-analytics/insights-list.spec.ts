import { InsightPage } from '../../page-models/insightPage'
import { randomString } from '../../utils'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Insights list', () => {
    test.setTimeout(60_000)

    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true, skip_onboarding: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.login(page, workspace!)
    })

    test('Can create, search, and open an insight', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightName = randomString('list-test')

        await test.step('create and save a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
            await expect(insight.editButton).toBeVisible()
        })

        await test.step('search for the insight and navigate to it', async () => {
            await insight.goToList()
            await page.getByPlaceholder('Search').fill(insightName)
            // Wait for the debounced search to fire (loader appears) then complete (loader gone)
            await page
                .locator('.LemonTableLoader')
                .waitFor({ state: 'visible' })
                .catch(() => {})
            await expect(page.locator('.LemonTableLoader')).toHaveCount(0)
            const link = page.locator('table tbody tr').first().getByRole('link', { name: insightName })
            await expect(link).toBeVisible()
            await link.click()
            await page.waitForURL(/\/insights\/\w+/)

            await expect(insight.topBarName).toContainText(insightName, { timeout: 15_000 })
        })
    })

    test('Can delete an insight from the list', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightName = randomString('to-delete')

        await test.step('create an insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
        })

        await test.step('delete the insight via row menu', async () => {
            await insight.goToList()
            await page.getByPlaceholder('Search').fill(insightName)
            await expect(page.getByText(insightName)).toBeVisible()
            await page.locator('table tbody tr').first().hover()
            await page.locator('table tbody tr').first().getByTestId('more-button').click()
            await page.getByRole('button', { name: 'Delete' }).click()
        })

        await test.step('verify the insight is removed', async () => {
            await expect(page.getByText('There are no insights matching')).toBeVisible()
        })
    })

    test('Can duplicate an insight from the list', async ({ page }) => {
        const insight = new InsightPage(page)
        const insightName = randomString('to-duplicate')

        await test.step('create an insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
            await insight.editName(insightName)
            await insight.save()
        })

        await test.step('duplicate the insight via row menu', async () => {
            await insight.goToList()
            await page.getByPlaceholder('Search').fill(insightName)
            await expect(page.getByText(insightName)).toBeVisible()
            await page.locator('table tbody tr').first().hover()
            await page.locator('table tbody tr').first().getByTestId('more-button').click()
            await page.getByRole('button', { name: 'Duplicate' }).click()
        })

        await test.step('verify duplicate was created', async () => {
            await expect(page.getByText(`${insightName} (copy)`).first()).toBeVisible()
        })
    })
})
