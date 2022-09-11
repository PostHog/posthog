import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const profileBubblesTestCases = [
    'one-bubble',
    'multiple-bubbles-with-tooltip',
    'multiple-bubbles-with-no-images',
    'multiple-bubbles-at-limit',
    'multiple-bubbles-overflowing-by-one',
    'multiple-bubbles-overflowing-by-two',
]

profileBubblesTestCases.forEach((testCase) => {
    test(`lemon profile-bubbles ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-profile-bubbles"]').click()
        await page.locator(`[data-item-id="lemon-ui-profile-bubbles--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon profile-bubbles ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-profile-bubbles"]').click()
        await page.locator(`[data-item-id="lemon-ui-profile-bubbles--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
