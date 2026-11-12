import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

import { sceneHidesProjectNotice } from './ProjectNoticeSlot'

describe('sceneHidesProjectNotice', () => {
    test.each([Scene.ErrorAccessDenied, Scene.ErrorProjectAccessDenied, Scene.ErrorProjectUnavailable])(
        'hides the notice when %s replaces a routed scene that shows it',
        (errorScene) => {
            expect(sceneHidesProjectNotice(sceneConfigurations[Scene.Dashboards], errorScene)).toBe(true)
        }
    )

    it('shows the notice on a scene that does not hide it', () => {
        expect(sceneHidesProjectNotice(sceneConfigurations[Scene.Dashboards], Scene.Dashboards)).toBe(false)
    })
})
