import { Scene } from 'scenes/sceneTypes'

import { shouldHideWizardSyncCard } from './WizardSyncFab'

describe('WizardSyncFab', () => {
    test.each([
        { scene: Scene.Quickstart, expected: true },
        { scene: Scene.Onboarding, expected: false },
        { scene: Scene.Dashboard, expected: false },
    ])('returns $expected for $scene', ({ scene, expected }) => {
        expect(shouldHideWizardSyncCard(scene)).toBe(expected)
    })
})
