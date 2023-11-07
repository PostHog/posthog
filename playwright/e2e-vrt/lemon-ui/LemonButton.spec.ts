import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Lemon Button', () => {
    // TODO: Remove when our Storybook test runner supports play tests
    test('displays hover state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Button', 'Default'))
        await storyPage.expectComponentScreenshot({ pseudo: { hover: true } })
    })

    test('displays disabled reason correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Button', 'Disabled With Reason'))
        await storyPage.storyRoot.locator('.LemonButton').nth(2).hover()
        await storyPage.page.getByRole('tooltip').waitFor()
        await storyPage.expectComponentScreenshot({ pseudo: { hover: true } })
    })
})
