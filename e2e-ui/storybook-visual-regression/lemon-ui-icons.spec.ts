import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

//todo how to screenshot/tests all icons in library

const iconBubbleTypesTestCases = [
    'library',
    'icon-with-count-bubble',
    'icon-with-count-hiding-zero',
    'icon-with-count-showing-zero',
    'icon-with-count-overflowing',
]

iconBubbleTypesTestCases.forEach((testCase) => {
    test(`lemon icons ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-icons"]').click()
        await page.locator(`[data-item-id="lemon-ui-icons--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(`lemon icons ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-icons"]').click()
        await page.locator(`[data-item-id="lemon-ui-icons--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
