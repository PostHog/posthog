import { Page } from '@playwright/test'

import { expect, test } from '../../utils/playwright-test-base'

test.describe('Survey Settings', () => {
    test.beforeEach(async ({ page }) => {
        await page.goToMenuItem('surveys')
    })

    async function enableSurveysIfDisabled(page: Page): Promise<void> {
        const switchElement = page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')
        const classAttribute = await switchElement.getAttribute('class')
        const isSurveyEnabled = classAttribute ? classAttribute.includes('LemonSwitch--checked') : false

        if (!isSurveyEnabled) {
            await page.locator('[data-attr="opt-in-surveys-switch"]').click()
            await expect(page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')).toHaveClass(
                /LemonSwitch--checked/
            )
        }
    }

    test('enables and disables surveys', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.getByRole('tab', { name: 'Settings' }).locator('div').click()

        await enableSurveysIfDisabled(page)

        await page.getByTestId('opt-in-surveys-switch').click()
        await expect(page.getByText('Surveys are currently disabled')).not.toBeVisible()
        await page.getByTestId('opt-in-surveys-switch').click()

        await expect(page.getByTestId('opt-in-surveys-switch')).not.toBeChecked()
        await expect(page.getByText('Surveys are currently disabled')).toBeVisible()

        await page.waitForTimeout(2000)

        await page.getByTestId('opt-in-surveys-switch').click()
        await expect(page.getByText('Surveys are currently disabled')).not.toBeVisible()
    })

    test('changes survey settings in the org settings page', async ({ page }) => {
        await expect(page.locator('h1')).toContainText('Surveys')
        await expect(page).toHaveTitle('Surveys • PostHog')

        await page.goToMenuItem('settings')
        await page.locator('#main-content').getByRole('link', { name: 'Surveys', exact: true }).click()
        await enableSurveysIfDisabled(page)

        await page.locator('[data-attr="opt-in-surveys-switch"]').click()
        await expect(page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')).not.toHaveClass(
            /LemonSwitch--checked/
        )

        await page.locator('[data-attr="opt-in-surveys-switch"]').click()
        await expect(page.locator('.LemonSwitch:has([data-attr="opt-in-surveys-switch"])')).toHaveClass(
            /LemonSwitch--checked/
        )
    })
})
