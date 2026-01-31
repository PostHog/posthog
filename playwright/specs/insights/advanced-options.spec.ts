import { InsightPage } from '../../page-models/insightPage'
import { PlaywrightWorkspaceSetupResult, expect, test } from '../../utils/workspace-test-base'

test.describe('Advanced Options', () => {
    let workspace: PlaywrightWorkspaceSetupResult | null = null

    test.beforeAll(async ({ playwrightSetup }) => {
        workspace = await playwrightSetup.createWorkspace({ use_current_time: true })
    })

    test.beforeEach(async ({ page, playwrightSetup }) => {
        await playwrightSetup.loginAndNavigateToTeam(page, workspace!)
    })

    test('toggle use person properties from query time', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('expand Advanced options section', async () => {
            await page.getByText('Advanced options').click()
        })

        await test.step('toggle Use person properties from query time', async () => {
            const toggle = page.getByRole('switch').first()
            await toggle.click()
            await expect(toggle.locator('..')).toHaveClass(/LemonSwitch--checked/)
        })
    })

    test('add a goal line to the chart', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('expand Advanced options section', async () => {
            await page.getByText('Advanced options').click()
        })

        await test.step('click Add goal line button', async () => {
            await page.getByRole('button', { name: 'Add goal line' }).click()
        })

        await test.step('enter goal value and label', async () => {
            const valueInput = page.locator('input[type="number"]').last()
            await valueInput.fill('100')

            const labelInput = page.getByPlaceholder('Label').last()
            await labelInput.fill('Target')
        })

        await test.step('verify goal line is configured', async () => {
            await expect(page.locator('input[type="number"]').last()).toHaveValue('100')
            await expect(page.getByPlaceholder('Label').last()).toHaveValue('Target')
        })
    })

    test('remove a goal line', async ({ page }) => {
        const insight = new InsightPage(page)

        await test.step('create a new Trends insight', async () => {
            await insight.goToNewTrends()
            await insight.trends.waitForChart()
        })

        await test.step('expand Advanced options and add a goal line', async () => {
            await page.getByText('Advanced options').click()
            await page.getByRole('button', { name: 'Add goal line' }).click()
            const valueInput = page.locator('input[type="number"]').last()
            await valueInput.fill('100')
            await expect(page.locator('input[type="number"]').last()).toHaveValue('100')
        })

        await test.step('remove the goal line', async () => {
            await page.getByRole('button', { name: 'Delete goal line' }).click()
            await expect(page.locator('input[type="number"]')).toHaveCount(0)
        })
    })
})
