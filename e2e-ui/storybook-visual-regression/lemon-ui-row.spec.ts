import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const rowTestCases = [
    'default',
    'text-only',
    'icon-only',
    'outlined',
    'success',
    'warning',
    'danger',
    'disabled',
    'loading',
    'small',
    'tall',
    'large',
    'full-width',
    'with-side-icon',
    'with-tooltip',
    'with-extended-content',
]

rowTestCases.forEach((testCase) => {
    test(`lemon row ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-row"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-row--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon row ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-row"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-row--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
