import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'

test.describe('Survey Settings', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('surveys')
    })

    async function toggleSurveysSettingsAndWaitResponse(page: Page): Promise<void> {
        await page.locator('[data-attr="opt-in-surveys-switch"]').click()
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeDisabled()
        await expect(page.getByText('Surveys opt in updated')).toBeVisible()
        await page.getByTestId('toast-close-button').click()
        await expect(page.getByText('Surveys opt in updated')).not.toBeVisible()
    }

    test('toggles survey opt in on the survey settings page', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')
        await page.getByRole('tab', { name: 'Settings' }).locator('div').click()
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeDisabled()
        await expect(page.getByText('Surveys opt in updated')).not.toBeVisible()
        await toggleSurveysSettingsAndWaitResponse(page)
        await toggleSurveysSettingsAndWaitResponse(page)
    })

    test('toggles survey opt in on the org settings page', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.goToMenuItem('settings')
        await page.locator('#main-content').getByRole('link', { name: 'Surveys', exact: true }).click()
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeDisabled()
        await expect(page.getByText('Surveys opt in updated')).not.toBeVisible()
        await toggleSurveysSettingsAndWaitResponse(page)
        await toggleSurveysSettingsAndWaitResponse(page)
    })
})
