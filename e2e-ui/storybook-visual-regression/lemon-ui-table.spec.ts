import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

const tableTestCases = [
    'basic',
    'grouped',
    'empty',
    'paginated-automatically',
    'with-expandable-rows',
    'small',
    'x-small',
    'embedded',
    'borderless',
    'loading',
    'empty-loading',
    'empty-loading-with-many-skeleton-rows',
    'without-header',
    'without-uppercasing-in-header',
    'with-color-coded-rows',
    'with-highlighted-rows',
    'with-mandatory-sorting',
]

tableTestCases.forEach((testCase) => {
    test(`lemon table ${testCase}`, async ({ page }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-table"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-table--${testCase}"]`).click()

        await page.locator('button:has-text("Canvas")').click()
        await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
    })

    test(` lemon table ${testCase} should only have allow-listed automatically detectable accessibility issues`, async ({
        page,
    }) => {
        await page.goto(storybookURL)
        await page.locator('[data-item-id="lemon-ui-lemon-table"]').click()
        await page.locator(`[data-item-id="lemon-ui-lemon-table--${testCase}"]`).click()

        const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

        expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
    })
})
