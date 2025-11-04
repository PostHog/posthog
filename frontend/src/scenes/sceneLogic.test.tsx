import { kea, path } from 'kea'
import { router } from 'kea-router'
import { expectLogic, partial, truth } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { sceneLogic } from './sceneLogic'
import type { logicType } from './sceneLogic.testType'

const Component = (): JSX.Element => <div />
const logic = kea<logicType>([path(['scenes', 'sceneLogic', 'test'])])
const sceneImport = (): any => ({ scene: { component: Component, logic: logic } })

const testScenes: Record<string, () => any> = {
    [Scene.DataManagement]: sceneImport,
    [Scene.Settings]: sceneImport,
}

describe('sceneLogic', () => {
    let logic: ReturnType<typeof sceneLogic.build>

    beforeEach(async () => {
        initKeaTests()
        localStorage.clear()
        sessionStorage.clear()
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        router.actions.push(urls.eventDefinitions())
        logic = sceneLogic({ scenes: testScenes })
        logic.mount()
    })

    it('has preloaded some scenes', async () => {
        const preloadedScenes = [Scene.Error404, Scene.ErrorNetwork, Scene.ErrorProjectUnavailable]
        await expectLogic(logic).toMatchValues({
            exportedScenes: truth(
                (obj: Record<string, any>) =>
                    Object.keys(obj).filter((key) => preloadedScenes.includes(key as Scene)).length === 3
            ),
        })
    })

    it('changing URL runs openScene, loadScene and setScene', async () => {
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            sceneId: Scene.DataManagement,
        })
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).toDispatchActions(['openScene', 'loadScene', 'setScene']).toMatchValues({
            sceneId: Scene.Settings,
        })
    })

    it('persists the loaded scenes', async () => {
        const expectedAnnotation = partial({
            component: expect.any(Function),
            logic: expect.any(Function),
        })

        const expectedSettings = partial({
            component: expect.any(Function),
            logic: expect.any(Function),
        })

        await expectLogic(logic).delay(1)

        expect(logic.values.exportedScenes).toMatchObject({
            [Scene.DataManagement]: expectedAnnotation,
        })
        router.actions.push(urls.settings('user'))
        await expectLogic(logic).delay(1)

        expect(logic.values.exportedScenes).toMatchObject({
            [Scene.DataManagement]: expectedAnnotation,
            [Scene.Settings]: expectedSettings,
        })
    })

    it('can pin and unpin tabs, syncing storage', async () => {
        const teamId = teamLogic.values.currentTeamId ?? 'null'
        const pinnedStorageKey = `scene-tabs-pinned-state-${teamId}`

        logic.actions.setTabs([
            {
                id: 'tab-1',
                active: true,
                pathname: '/a',
                search: '',
                hash: '',
                title: 'Tab A',
                iconType: 'blank',
            },
            {
                id: 'tab-2',
                active: false,
                pathname: '/b',
                search: '',
                hash: '',
                title: 'Tab B',
                iconType: 'blank',
            },
        ])

        logic.actions.pinTab('tab-2')

        await expectLogic(logic).toMatchValues({
            tabs: [
                expect.objectContaining({ id: 'tab-2', pinned: true }),
                expect.objectContaining({ id: 'tab-1', pinned: false }),
            ],
        })

        const storedPinned = JSON.parse(localStorage.getItem(pinnedStorageKey) ?? '[]')
        expect(storedPinned).toEqual([expect.objectContaining({ id: 'tab-2', pathname: '/b', pinned: true })])

        logic.actions.unpinTab('tab-2')

        await expectLogic(logic).toMatchValues({
            tabs: [
                expect.objectContaining({ id: 'tab-1', pinned: false }),
                expect.objectContaining({ id: 'tab-2', pinned: false }),
            ],
        })

        expect(localStorage.getItem(pinnedStorageKey)).toBeNull()
    })
})
