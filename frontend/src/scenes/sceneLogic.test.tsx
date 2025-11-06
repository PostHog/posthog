import { kea, path } from 'kea'
import { router } from 'kea-router'
import { expectLogic, partial, truth } from 'kea-test-utils'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { sceneLogic } from './sceneLogic'
import type { logicType } from './sceneLogic.testType'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
        update: jest.fn(),
    },
}))

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
        jest.clearAllMocks()
        initKeaTests()
        localStorage.clear()
        sessionStorage.clear()
        ;(api.get as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        ;(api.update as jest.Mock).mockResolvedValue({ tabs: [], homepage: null })
        await expectLogic(teamLogic).toDispatchActions(['loadCurrentTeamSuccess'])
        featureFlagLogic.mount()
        router.actions.push(urls.eventDefinitions())
        logic = sceneLogic.build({ scenes: testScenes })
        // Simulate a fresh mount so that stored tabs are read from localStorage.
        logic.cache.tabsLoaded = false
        logic.mount()
        await expectLogic(logic).delay(1)
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
        await expectLogic(logic).delay(600)

        const storedPinned = JSON.parse(localStorage.getItem(pinnedStorageKey) ?? '{}')
        expect(storedPinned).toEqual({
            tabs: [expect.objectContaining({ id: 'tab-2', pathname: '/b', pinned: true })],
            homepage: null,
        })

        logic.actions.setHomepage(logic.values.tabs[0])

        await expectLogic(logic).delay(600)

        expect(JSON.parse(localStorage.getItem(pinnedStorageKey) ?? '{}')).toEqual({
            tabs: [expect.objectContaining({ id: 'tab-2', pathname: '/b', pinned: true })],
            homepage: expect.objectContaining({ id: 'tab-2', pinned: true }),
        })

        logic.actions.unpinTab('tab-2')

        await expectLogic(logic).toMatchValues({
            tabs: expect.arrayContaining([
                expect.objectContaining({ id: 'tab-1', pinned: false }),
                expect.objectContaining({ id: 'tab-2', pinned: false }),
            ]),
        })
        await expectLogic(logic).delay(600)
        expect(localStorage.getItem(pinnedStorageKey)).toBeNull()
        expect(logic.values.homepage).toBeNull()
    })

    it('removes pinned tabs when receiving updated storage without them', async () => {
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

        logic.actions.pinTab('tab-1')
        logic.actions.pinTab('tab-2')

        await expectLogic(logic).toMatchValues({
            tabs: [
                expect.objectContaining({ id: 'tab-1', pinned: true }),
                expect.objectContaining({ id: 'tab-2', pinned: true }),
            ],
        })

        const remoteState = {
            tabs: [
                {
                    id: 'tab-1',
                    pathname: '/a',
                    search: '',
                    hash: '',
                    title: 'Tab A',
                    iconType: 'blank',
                    pinned: true,
                    active: false,
                },
            ],
            homepage: null,
        }

        localStorage.setItem(pinnedStorageKey, JSON.stringify(remoteState))
        window.dispatchEvent(
            new StorageEvent('storage', {
                key: pinnedStorageKey,
                newValue: JSON.stringify(remoteState),
            })
        )

        await expectLogic(logic).toMatchValues({
            tabs: [expect.objectContaining({ id: 'tab-1', pinned: true })],
        })
    })

    it('does not duplicate pinned tab when unpinning after reordering', async () => {
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
            {
                id: 'tab-3',
                active: false,
                pathname: '/c',
                search: '',
                hash: '',
                title: 'Tab C',
                iconType: 'blank',
            },
        ])

        logic.actions.pinTab('tab-2')
        logic.actions.pinTab('tab-3')

        await expectLogic(logic).toMatchValues({
            tabs: expect.arrayContaining([
                expect.objectContaining({ id: 'tab-2', pinned: true }),
                expect.objectContaining({ id: 'tab-3', pinned: true }),
                expect.objectContaining({ id: 'tab-1', pinned: false }),
            ]),
        })

        logic.actions.reorderTabs('tab-3', 'tab-2')

        await expectLogic(logic).toMatchValues({
            tabs: expect.arrayContaining([
                expect.objectContaining({ id: 'tab-3', pinned: true }),
                expect.objectContaining({ id: 'tab-2', pinned: true }),
                expect.objectContaining({ id: 'tab-1', pinned: false }),
            ]),
        })

        const stalePinnedState = {
            tabs: logic.values.tabs
                .filter((tab) => tab.pinned)
                .map((tab) => ({
                    id: tab.id,
                    pathname: tab.pathname,
                    search: tab.search,
                    hash: tab.hash,
                    title: tab.title,
                    active: false,
                    iconType: tab.iconType,
                    pinned: true,
                })),
            homepage: null,
        }

        logic.actions.unpinTab('tab-3')

        await expectLogic(logic).toMatchValues({
            tabs: expect.arrayContaining([
                expect.objectContaining({ id: 'tab-2', pinned: true }),
                expect.objectContaining({ id: 'tab-1', pinned: false }),
                expect.objectContaining({ id: 'tab-3', pinned: false }),
            ]),
        })

        logic.actions.setPinnedStateFromBackend(stalePinnedState)

        const tab3Instances = logic.values.tabs.filter((tab) => tab.id === 'tab-3')
        const pinnedTabs = logic.values.tabs.filter((tab) => tab.pinned)

        expect(tab3Instances).toHaveLength(1)
        expect(tab3Instances[0].pinned).toBe(false)
        expect(pinnedTabs.map((tab) => tab.id)).not.toContain('tab-3')
    })
    it('hydrates pinned tabs stored under legacy personal key', async () => {
        const teamId = teamLogic.values.currentTeamId ?? 'null'
        const pinnedStorageKey = `scene-tabs-pinned-state-${teamId}`

        logic.unmount()

        sessionStorage.clear()

        localStorage.setItem(
            pinnedStorageKey,
            JSON.stringify({
                personal: [
                    {
                        id: 'legacy-tab',
                        pathname: '/legacy',
                        search: '',
                        hash: '',
                        title: 'Legacy tab',
                        iconType: 'blank',
                        pinned: true,
                    },
                ],
                homepage: {
                    id: 'legacy-tab',
                    pathname: '/legacy',
                    search: '',
                    hash: '',
                    title: 'Legacy tab',
                    iconType: 'blank',
                    pinned: true,
                },
            })
        )
        ;(api.get as jest.Mock).mockReturnValue(new Promise(() => {}))

        logic = sceneLogic.build({ scenes: testScenes })
        logic.cache.tabsLoaded = false
        logic.mount()

        await expectLogic(logic).toDispatchActions(['setTabs'])

        await expectLogic(logic).delay(0)

        expect(logic.values.tabs).toEqual(
            expect.arrayContaining([expect.objectContaining({ id: 'legacy-tab', pinned: true })])
        )
        expect(logic.values.homepage).toEqual(expect.objectContaining({ id: 'legacy-tab', pinned: true }))
    })
})
