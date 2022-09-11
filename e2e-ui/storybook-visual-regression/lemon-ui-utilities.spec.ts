import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const utilitiesTestCases = [
    'flex',
    'space-and-gap',
    'individual-spacing',
    'dimensions',
    'text-size',
    'text-font',
    'text-weight',
    'widths',
    'heights',
    'absolute-positioning',
]

utilitiesTestCases.forEach((testCase) => {
    test(`lemon utilities ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-utilities"]').click()
        await page.locator(`[data-item-id="lemon-ui-utilities--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon utilities ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-utilities"]').click()
        await page.locator(`[data-item-id="lemon-ui-utilities--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
