import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const bubbleTestCases = ['standard', 'over-nine', 'show-zero', 'positioning', 'sizes']

bubbleTestCases.forEach((testCase) => {
    test(`lemon bubble ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-bubble"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-bubble--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon lemon-bubble ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-bubble"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-bubble--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
