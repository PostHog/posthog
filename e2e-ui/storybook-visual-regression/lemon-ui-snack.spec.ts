import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const snackTestCases = ['default', 'complex-content', 'overflow-options']

snackTestCases.forEach((testCase) => {
    test(`lemon snack ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-snack"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-snack--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon snack ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-snack"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-snack--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
