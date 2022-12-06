import { expect, test } from '@playwright/test'

const storybookUrl: string = process.env.STORYBOOK_URL || 'http://localhost:6006'

test.describe('Lemon Button', () => {
    test('displays the button correctly', async ({ page }) => {
        const storyId = 'lemon-ui-lemon-button--default'
        const storyUrl = `${storybookUrl}/iframe.html?id=${storyId}&viewMode=story`
        await page.goto(storyUrl)

        await page.evaluate(() => {
            // what?: don't expand the container
            // why?: limits screenshots to the component's size
            const element = document.getElementById('root')
            if (element) {
                element.style.display = 'inline-block'
            }

            // what?: make body transparent
            // why?: allows taking screenshots without background
            document.body.style.background = 'transparent'
        })

        await page.pause()

        const locator = page.locator('#root')
        await expect(locator).toHaveScreenshot({ omitBackground: true })
    })

    // TODO: hover and focus state - https://www.chromatic.com/docs/hoverfocus
})
