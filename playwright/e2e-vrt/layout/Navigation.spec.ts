import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Navigation', () => {
    test('App Page With Side Bar Hidden (Desktop)', async ({ storyPage }) => {
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Hidden'))
        await storyPage.expectFullPageScreenshot()
    })

    test('App Page With Side Bar Shown (Desktop)', async ({ storyPage }) => {
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Shown'))
        await storyPage.expectFullPageScreenshot()
    })

    test('App Page With Side Bar Hidden (Mobile)', async ({ storyPage }) => {
        await storyPage.resizeToMobile()
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Hidden'))
        await storyPage.expectFullPageScreenshot()
    })

    test('App Page With Side Bar Shown (Mobile)', async ({ storyPage }) => {
        await storyPage.resizeToMobile()
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Shown'))
        await storyPage.expectFullPageScreenshot()
    })
})
