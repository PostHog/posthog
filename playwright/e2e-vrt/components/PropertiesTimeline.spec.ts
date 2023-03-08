import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Properties Timeline', () => {
    test('Multiple Points for One Person Property', async ({ storyPage }) => {
        await storyPage.goto(toId('Components/Properties Timeline', 'Multiple Points for One Person Property'))
        await storyPage.expectComponentScreenshot()
    })

    test('One Point for One Person Property', async ({ storyPage }) => {
        await storyPage.goto(toId('Components/Properties Timeline', 'One Point for One Person Property'))
        await storyPage.expectComponentScreenshot()
    })

    test('No Points for No Person Properties', async ({ storyPage }) => {
        await storyPage.goto(toId('Components/Properties Timeline', 'No Points for No Person Properties'))
        await storyPage.expectComponentScreenshot()
    })
})
