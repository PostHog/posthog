import { expect, test } from '@playwright/test'

// eslint-disable-next-line @typescript-eslint/no-non-null-assertion
const storybookUrl: string = process.env.STORYBOOK_URL!

test.describe('insights vrt', () => {
    test('displays the trends line insight correctly', async ({ page }) => {
        const storyId = 'scenes-app-insights--trends-line'
        const storyUrl = `${storybookUrl}/iframe.html?id=${storyId}&viewMode=story`
        await page.goto(storyUrl)

        await expect(page).toHaveScreenshot('full.png', { fullPage: true })

        const content = page.locator('.main-app-content')
        await expect(content).toHaveScreenshot('content.png')
    })

    // TODO: hover
})
