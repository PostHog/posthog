import { toId } from '../../helpers/storybook'

import { test } from '../../fixtures/storybook'

test.describe('Lemon Button', () => {
    test('displays correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Button', 'Default'))
        await storyPage.screenshotStoryRoot()
    })

    test('displays hover state correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Button', 'Default'))
        await storyPage.screenshotStoryRoot({ pseudo: { hover: true } })
    })
})
