import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { violationFingerprints } from '../accessibility'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

test(`lemon calendar`, async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-calendar"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar"]').click() // sub menu

    await expect(page).toHaveScreenshot({ maxDiffPixels: 100, fullPage: true })
})

test(`lemon calendar multiple months`, async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-calendar"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar"]').click() // sub menu
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar--multiple-months"]').click()

    await expect(page).toHaveScreenshot({ maxDiffPixels: 100, fullPage: true })
})

test(`lemon calendar custom styles`, async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-calendar"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar"]').click() // sub menu
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar--custom-styles"]').click()

    await expect(page).toHaveScreenshot({ maxDiffPixels: 100, fullPage: true })
})

test(`lemon calendar range`, async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-calendar"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar-range--lemon-calendar-range"]').click()

    await expect(page).toHaveScreenshot({ maxDiffPixels: 100, fullPage: true })
})

test(`lemon calendar select`, async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-calendar"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar-select--lemon-calendar-select"]').click()

    await expect(page).toHaveScreenshot({ maxDiffPixels: 100, fullPage: true })
})

test(`lemon calendar should only have allow-listed automatically detectable accessibility issues`, async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-calendar"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-calendar-lemon-calendar"]').click() // sub menu

    const accessibilityScanResults = await new AxeBuilder({ page }).exclude('#bottom-notice').analyze()

    expect(violationFingerprints(accessibilityScanResults)).toMatchSnapshot()
})
