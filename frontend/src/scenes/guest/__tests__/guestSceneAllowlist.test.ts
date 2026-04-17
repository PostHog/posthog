import { Scene } from 'scenes/sceneTypes'

import { GUEST_ALLOWED_SCENES } from '../guestSceneAllowlist'

describe('guestSceneAllowlist', () => {
    it('contains the expected scenes', () => {
        expect([...GUEST_ALLOWED_SCENES].sort()).toMatchSnapshot()
    })

    it.each([
        [Scene.Dashboard, true],
        [Scene.GuestLanding, true],
        [Scene.GuestNotFound, true],
        [Scene.Settings, true],
    ] as const)('allows scene %s = %s', (scene, expected) => {
        expect(GUEST_ALLOWED_SCENES.has(scene)).toBe(expected)
    })

    it.each([Scene.FeatureFlags, Scene.Experiments, Scene.Cohorts, Scene.DataWarehouseSource] as const)(
        'blocks scene %s',
        (scene) => {
            expect(GUEST_ALLOWED_SCENES.has(scene)).toBe(false)
        }
    )
})
