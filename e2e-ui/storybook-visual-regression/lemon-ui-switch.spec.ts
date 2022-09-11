import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const switchTestCases = ['basic', 'overview', 'standalone', 'bordered', 'disabled']

switchTestCases.forEach((testCase) => {
    test(`lemon switch ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-switch"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-switch--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon switch ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-switch"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-switch--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
