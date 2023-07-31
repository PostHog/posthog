import { toId } from '../../helpers/storybook'
import { test } from '../../fixtures/storybook'

test.describe('session replay', () => {
    const replayScenes = [
        'Recordings List',
        'Recordings Play Lists',
        'Recordings Play List No Pinned Recordings',
        'Recordings Play List With Pinned Recordings',
        'Session Recording In List',
    ]
    for (const scene of replayScenes) {
        test(`displays ${scene} page`, async ({ storyPage }) => {
            await storyPage.goto(toId('Scenes-App/Recordings', scene))
            await storyPage.expectFullPageScreenshot()
        })
    }
})
