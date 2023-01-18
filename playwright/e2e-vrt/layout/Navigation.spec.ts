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
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Hidden'))
        await storyPage.page.setViewportSize({ width: 375, height: 667 }) // iPhone 6/7/8
        await storyPage.expectFullPageScreenshot()
    })

    test('App Page With Side Bar Shown (Mobile)', async ({ storyPage }) => {
        await storyPage.goto(toId('Layout/Navigation', 'App Page With Side Bar Shown'))
        await storyPage.page.setViewportSize({ width: 375, height: 667 }) // iPhone 6/7/8
        await storyPage.expectFullPageScreenshot()
    })
})
