import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Navigation', () => {
    // TODO: Remove when our Storybook test runner supports mobile viewports
    test('App Page With Side Bar Hidden (Mobile)', async ({ storyPage }) => {
        await storyPage.resizeToMobile()
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Hidden'))
        await storyPage.mainAppContent.waitFor()
        await storyPage.expectFullPageScreenshot()
    })

    test('App Page With Side Bar Shown (Mobile)', async ({ storyPage }) => {
        await storyPage.resizeToMobile()
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Shown'))
        await storyPage.mainAppContent.waitFor()
        await storyPage.expectFullPageScreenshot()
    })
})
