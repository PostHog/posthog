import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Lemon Badge', () => {
    test('Positioning story', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Badge/Lemon Badge', 'Positioning'))
        await storyPage.expectComponentScreenshot()
    })

    test('Sizes story', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Badge/Lemon Badge', 'Sizes'))
        await storyPage.expectComponentScreenshot()
    })
    test('Status story', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Badge/Lemon Badge', 'Status'))
        await storyPage.expectComponentScreenshot()
    })

    test('Active story', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Badge/Lemon Badge', 'Active'))
        await storyPage.expectComponentScreenshot()
    })
})
