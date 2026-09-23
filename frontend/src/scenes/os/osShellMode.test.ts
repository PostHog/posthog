import type { SceneConfig } from 'scenes/sceneTypes'

import { resolveOsShellMode } from './osShellMode'

const appScene: SceneConfig = { projectBased: true, name: 'Insight' }
const plainScene: SceneConfig = { projectBased: true, name: 'Onboarding', layout: 'plain' }

describe('resolveOsShellMode', () => {
    test.each([
        ['flag on, app scene', 'full', true, false, appScene, false, 'os'],
        ['flag on, persisted zen mode', 'zen', true, false, appScene, false, 'os'],
        ['flag off', 'full', false, false, appScene, false, 'full'],
        ['flag on, scene that owns the page', 'minimal', true, false, plainScene, false, 'minimal'],
        ['flag on, organization unavailable', 'minimal', true, false, appScene, true, 'minimal'],
        ['flag on, inside an OS window', 'full', true, true, appScene, false, 'framed'],
        ['flag off, inside an OS window', 'full', false, true, appScene, false, 'framed'],
    ] as const)(
        '%s',
        (_description, regularMode, osShellEnabled, framed, sceneConfig, organizationUnavailable, expected) => {
            expect(
                resolveOsShellMode(regularMode, { osShellEnabled, framed, sceneConfig, organizationUnavailable })
            ).toBe(expected)
        }
    )
})
