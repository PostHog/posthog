import { act, cleanup, render } from '@testing-library/react'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'

import { initKeaTests } from '~/test/init'

import { ScenePanel } from './SceneLayout'
import { sceneLayoutLogic } from './sceneLayoutLogic'

describe('ScenePanel', () => {
    let layoutLogic: ReturnType<typeof sceneLayoutLogic.build>
    let host: HTMLDivElement

    beforeEach(() => {
        initKeaTests()
        sceneLogic().mount()
        layoutLogic = sceneLayoutLogic()
        layoutLogic.mount()
        host = document.createElement('div')
        document.body.appendChild(host)
        act(() => {
            sceneLogic.actions.setScene(Scene.Experiment, undefined, { params: {} } as any)
            layoutLogic.actions.registerScenePanelElement('inline', host)
        })
    })

    afterEach(() => {
        cleanup()
        host.remove()
    })

    it('clears the shared host when the scene it belongs to is no longer active', () => {
        render(
            <ScenePanel>
                <button>Duplicate</button>
            </ScenePanel>
        )
        expect(host.textContent).toBe('Duplicate')

        // The owning scene lingers (a deferred teardown, or a slow chunk load for the next
        // scene) while the app has already moved on. Its actions must leave the shared host.
        act(() => {
            sceneLogic.actions.setScene(Scene.Dashboards, undefined, { params: {} } as any)
        })

        expect(host.textContent).toBe('')
        expect(layoutLogic.values.scenePanelIsPresent).toBe(false)
    })

    it('keeps the host open while any panel of the active scene is still mounted', () => {
        const { rerender } = render(
            <>
                <ScenePanel>
                    <button>First</button>
                </ScenePanel>
                <ScenePanel>
                    <button>Second</button>
                </ScenePanel>
            </>
        )
        expect(layoutLogic.values.scenePanelIsPresent).toBe(true)

        rerender(
            <>
                <ScenePanel>
                    <button>First</button>
                </ScenePanel>
            </>
        )

        expect(layoutLogic.values.scenePanelIsPresent).toBe(true)
        expect(host.textContent).toBe('First')
    })

    it('prefers the side panel host over the inline one while the side panel is mounted', () => {
        const sidePanelHost = document.createElement('div')
        document.body.appendChild(sidePanelHost)
        render(
            <ScenePanel>
                <button>Duplicate</button>
            </ScenePanel>
        )

        act(() => {
            layoutLogic.actions.registerScenePanelElement('sidePanel', sidePanelHost)
        })
        expect(sidePanelHost.textContent).toBe('Duplicate')
        expect(host.textContent).toBe('')

        act(() => {
            layoutLogic.actions.registerScenePanelElement('sidePanel', null)
        })
        expect(host.textContent).toBe('Duplicate')
        sidePanelHost.remove()
    })
})
