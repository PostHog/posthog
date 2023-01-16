import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Dashboards', () => {
    test('List', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Dashboards', 'List'))
        await storyPage.expectSceneScreenshot()
    })
})
