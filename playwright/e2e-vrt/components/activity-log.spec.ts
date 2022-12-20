import { toId } from '../../helpers/storybook'

import { test } from '../../fixtures/storybook'

test.describe('Activity Log', () => {
    test('displays feature flag activity', async ({ storyPage }) => {
        await storyPage.goto(toId('Components/ActivityLog', 'Feature Flag Activity'))
        await storyPage.expectComponentScreenshot()
    })

    test('displays insight activity', async ({ storyPage }) => {
        await storyPage.goto(toId('Components/ActivityLog', 'Insight Activity'))
        await storyPage.expectComponentScreenshot()
    })
})
