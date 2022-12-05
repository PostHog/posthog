import { expect, test } from '@playwright/test'

const storybookUrl: string = process.env.STORYBOOK_URL || 'http://localhost:6006'

test.describe('Lemon Button', () => {
    test('displays the button correctly', async ({ page }) => {
        const storyId = 'lemon-ui-lemon-button--default'
        const storyUrl = `${storybookUrl}/iframe.html?id=${storyId}&viewMode=story`
        await page.goto(storyUrl)

        const locator = page.locator('#root')
        await expect(locator).toHaveScreenshot()
    })

    // TODO: hover and focus state - https://www.chromatic.com/docs/hoverfocus
})
