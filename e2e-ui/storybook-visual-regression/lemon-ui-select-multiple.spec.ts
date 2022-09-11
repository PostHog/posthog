import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const selectMultipleTestCases = [
    'default',
    'multiple-select',
    'multiple-select-with-custom',
    'disabled',
    'loading',
    'no-options',
]

selectMultipleTestCases.forEach((testCase) => {
    test(`lemon Select Multiple ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-selectmultiple"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-selectmultiple--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon Select Multiple ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-selectmultiple"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-selectmultiple--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
