import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const buttonTestCases = [
    'default',
    'types-and-statuses',
    'no-padding',
    'text-only',
    'sizes',
    'sizes-icon-only',
    'disabled',
    'loading',
    'active',
    'menu-buttons',
    'with-side-icon',
    'full-width',
    'with-side-action',
    'as-links',
    'with-popup-to-the-right',
    'with-popup-to-the-bottom',
    'with-very-long-popup-to-the-bottom',
    'with-tooltip',
    'more',
]

buttonTestCases.forEach((testCase) => {
    test(`lemon button ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-button"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-button--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon lemon-button ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-button"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-button--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
