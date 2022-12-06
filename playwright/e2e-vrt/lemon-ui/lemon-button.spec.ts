import { toId } from '../../helpers/storybook'

import { test } from '../../fixtures/storybook'

test.describe('Lemon Button', () => {
    test('displays correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Lemon UI/Lemon Button', 'Default'))
        await storyPage.screenshotStoryRoot()
    })

    // TODO: hover and focus state - https://www.chromatic.com/docs/hoverfocus
})
