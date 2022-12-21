import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('Persons Modal', () => {
    test('displays list correctly', async ({ storyPage }) => {
        await storyPage.goto(toId('Scenes-App/Persons Modal', 'Persons Modal'))
        await storyPage.expectComponentScreenshot()
        // Expand first person to see properties
        await storyPage.page.click('[data-attr=persons-modal-expand-018339dc-735e-0000-fd6a-963eda28b90d]')
        await storyPage.expectComponentScreenshot()
    })
})
