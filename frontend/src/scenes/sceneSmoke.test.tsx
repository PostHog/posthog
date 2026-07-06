import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'
import { BindLogic, useMountedLogic, useValues } from 'kea'
import { router } from 'kea-router'
import posthog from 'posthog-js'
import { Component, type ReactNode } from 'react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { appScenes } from './appScenes'
import { sceneLogic } from './sceneLogic'
import { Scene } from './sceneTypes'

/*
The in-app browser-like scene tabs were removed: sceneLogic now mounts each scene with NO
`tabId` (and the bare scene has no `panelId`). A scene whose logic — or any logic it builds
during render — still requires such a prop is a runtime landmine that `tsc` and per-logic unit
tests do not catch, because both supply the prop. It surfaces two ways in production:

  1. The scene's own logic throws on build -> sceneLogic catches it and routes to Error404,
     reporting via `posthog.captureException` (e.g. a `tabAwareScene()` keyed on `props.tabId`).
  2. A logic built during the scene's render throws -> the scene's error boundary trips
     (e.g. `maxThreadLogic` keyed on `props.panelId` for the bare `/ai` scene).

This smoke test mounts each high-traffic scene the way production does — through sceneLogic and
the scene's own BindLogic, with no tabId/panelId — and fails on either shape: a missing-prop /
undefined-key message anywhere (case 2, and the recognisable form of case 1) AND silently
landing on an error scene (case 1 for any thrown message, since routing is data-independent —
only a scene-logic build throw turns a real route into Error404).
*/

const MISSING_PROP_OR_KEY = /must have a .* prop|Undefined key for logic/

// Routing path -> scene is data-independent, so reaching one of these means the scene's own
// logic threw on build, not that an entity was genuinely missing.
const ERROR_SCENES: string[] = [
    Scene.Error404,
    Scene.ErrorNetwork,
    Scene.ErrorProjectUnavailable,
    Scene.ErrorAccessDenied,
]

// Index routes resolve without an entity id; the entity routes additionally build the id-keyed
// scene logics (insightSceneLogic, dashboardLogic) that the index routes never construct.
const HIGH_TRAFFIC_SCENES: [name: string, path: string][] = [
    ['home', '/home'],
    ['max (/ai)', '/ai'],
    ['insights', '/insights'],
    ['insight (new)', '/insights/new'],
    ['dashboards', '/dashboard'],
    ['dashboard (detail)', '/dashboard/1'],
    ['persons', '/persons'],
    ['session replay', '/replay'],
    ['feature flags', '/feature_flags'],
    ['experiments', '/experiments'],
    ['surveys', '/surveys'],
    ['activity explore', '/activity/explore'],
    ['error tracking', '/error_tracking'],
    ['sql editor', '/sql'],
    ['engineering analytics', '/engineering-analytics'],
    ['project settings', '/settings/project'],
]

const renderErrors: Error[] = []

class CaptureBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
    override state = { failed: false }
    static getDerivedStateFromError(): { failed: boolean } {
        return { failed: true }
    }
    override componentDidCatch(error: Error): void {
        renderErrors.push(error)
    }
    override render(): ReactNode {
        return this.state.failed ? null : this.props.children
    }
}

function SceneHost(): JSX.Element | null {
    useMountedLogic(sceneLogic({ scenes: appScenes }))
    const { activeExportedScene, activeSceneComponentParams, activeSceneLogicProps, activeSceneId } =
        useValues(sceneLogic)

    if (!activeExportedScene?.component) {
        return null
    }
    const SceneComponent = activeExportedScene.component
    const element = <SceneComponent {...activeSceneComponentParams} />
    return activeExportedScene.logic ? (
        <BindLogic key={`bind-${activeSceneId}`} logic={activeExportedScene.logic} props={activeSceneLogicProps}>
            {element}
        </BindLogic>
    ) : (
        element
    )
}

describe('high-traffic scene smoke', () => {
    let consoleErrors: string[]
    let consoleErrorSpy: jest.SpyInstance
    let captureExceptionSpy: jest.SpyInstance

    beforeAll(() => {
        // jsdom has no CSS.supports; some scenes call it during render. Real browsers do.
        const css = (global as any).CSS ?? ((global as any).CSS = {})
        css.supports = css.supports ?? ((): boolean => false)
    })

    beforeEach(() => {
        useMocks({
            post: { '/api/environments/:team_id/query/': () => [200, { results: [] }] },
        })
        initKeaTests()
        renderErrors.length = 0
        consoleErrors = []
        consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation((...args) => {
            consoleErrors.push(args.map((a) => (a instanceof Error ? a.message : String(a))).join(' '))
        })
        captureExceptionSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
    })

    afterEach(() => {
        consoleErrorSpy.mockRestore()
        captureExceptionSpy.mockRestore()
        cleanup()
    })

    test.each(HIGH_TRAFFIC_SCENES)('%s mounts without a missing-prop / undefined-key crash', async (_name, path) => {
        router.actions.push(path)
        render(
            <CaptureBoundary>
                <SceneHost />
            </CaptureBoundary>
        )

        // Wait for the real scene component, not just `activeSceneId`: on a slow dynamic import
        // sceneLogic sets the id while `activeExportedScene` is still absent (SceneHost renders
        // null), so gating on the id alone can assert before the scene ever mounts.
        await waitFor(() => {
            expect(sceneLogic.findMounted()?.values.activeExportedScene?.component).toBeTruthy()
        })

        const activeSceneId = sceneLogic.findMounted()?.values.activeSceneId
        // Scope: the structural de-tab class — a logic keyed on / asserting an absent tabId/panelId
        // (the maxThreadLogic incident shape). Matched on the thrown message, plus an error-scene
        // landing for build throws of any message. Generic data-shape render errors (a component
        // hitting undefined fields from the deliberately-thin mock floor) are out of scope here —
        // asserting full render health would need exact-shape mocks for every product's endpoints.
        const fromRender = renderErrors.filter((e) => MISSING_PROP_OR_KEY.test(e.message)).map((e) => e.message)
        const fromConsole = consoleErrors.filter((s) => MISSING_PROP_OR_KEY.test(s))
        const fromCapture = captureExceptionSpy.mock.calls
            .map((call) => call[0])
            .filter((e): e is Error => e instanceof Error && MISSING_PROP_OR_KEY.test(e.message))
            .map((e) => e.message)

        expect({
            fromRender,
            fromConsole,
            fromCapture,
            routedToErrorScene: ERROR_SCENES.includes(activeSceneId ?? ''),
        }).toEqual({
            fromRender: [],
            fromConsole: [],
            fromCapture: [],
            routedToErrorScene: false,
        })
    })
})
