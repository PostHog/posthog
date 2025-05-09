import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'

test.describe('Survey Settings', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('surveys') // Assuming a helper function for navigation
    })

    async function enableSurveysIfDisabled(page: Page): Promise<void> {
        const switchElement = page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')
        const classAttribute = await switchElement.getAttribute('class')
        const isSurveyEnabled = classAttribute ? classAttribute.includes('LemonSwitch--checked') : false

        if (!isSurveyEnabled) {
            // Enable surveys if they're disabled
            await page.locator('[data-attr="opt-in-surveys-switch"]').click()
            // Verify it's now enabled
            await expect(page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')).toHaveClass(
                /LemonSwitch--checked/
            )
        }
    }

    test('enables and disable surveys', async ({ page }) => {
        // load an empty page
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.getByRole('tab', { name: 'Settings' }).locator('div').click()

        await enableSurveysIfDisabled(page)

        await page.getByTestId('opt-in-surveys-switch').click()
        await expect(page.getByText('Surveys are currently disabled')).not.toBeVisible()
        await page.getByTestId('opt-in-surveys-switch').click()

        // disable surveys
        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeChecked()
        await expect(page.getByText('Surveys are currently disabled')).toBeVisible()

        await page.waitForTimeout(2000)

        // enable it again
        await page.getByTestId('opt-in-surveys-switch').click()
        await expect(page.getByText('Surveys are currently disabled')).not.toBeVisible()
    })

    test('changes survey settings in the org settings page', async ({ page }) => {
        // load an empty pagawait page.goto('http://localhost:8080/login?next=/');e
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.goToMenuItem('settings')
        await page.locator('#main-content').getByRole('link', { name: 'Surveys', exact: true }).click()
        await enableSurveysIfDisabled(page)

        await page.locator('[data-attr="opt-in-surveys-switch"]').click()
        // Check that the parent LemonSwitch container doesn't have the checked class
        await expect(page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')).not.toHaveClass(
            /LemonSwitch--checked/
        )

        // enable it again
        await page.locator('[data-attr="opt-in-surveys-switch"]').click()

        // Check that the parent LemonSwitch container has the checked class
        await expect(page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')).toHaveClass(
            /LemonSwitch--checked/
        )
    })
})
