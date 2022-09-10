import { expect, test } from '@playwright/test'

const storybookURL: string = process.env.STORYBOOK_URL || 'https:storybook.posthog.net'

test('lemon button types and statuses', async ({ page }) => {
    await page.goto(storybookURL)
    await page.locator('[data-item-id="lemon-ui-lemon-button"]').click()
    await page.locator('[data-item-id="lemon-ui-lemon-button--types-and-statuses"]').click()

    await expect(page).toHaveScreenshot({ maxDiffPixels: 100 })
})
