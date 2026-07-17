import { getContext } from 'kea'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { NEW_INTERNAL_TAB } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { sceneTabsLogic } from './sceneTabsLogic'

jest.mock('lib/api', () => ({
    __esModule: true,
    default: {
        get: jest.fn(),
        update: jest.fn(),
    },
}))

describe('sceneTabsLogic', () => {
    let logic: ReturnType<typeof sceneTabsLogic.build>
    // tabs store project-prefixed paths (e.g. /project/997/insights)
    const prefixed = (path: string): string => addProjectIdIfMissing(path)

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        localStorage.clear()
        ;(api.get as jest.Mock).mockResolvedValue({})
        ;(api.update as jest.Mock).mockResolvedValue({})
        router.actions.push('/activity/explore')
        logic = sceneTabsLogic.build()
        logic.mount()
    })

    it('starts with a single tab pointing at the current location', () => {
        expect(logic.values.tabs).toHaveLength(1)
        expect(logic.values.tabs[0]).toMatchObject({ pathname: prefixed('/activity/explore'), active: true })
    })

    it('newTab appends an active tab and navigates to it', async () => {
        logic.actions.newTab()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.tabs).toHaveLength(2)
        expect(logic.values.activeTab).toMatchObject({ pathname: prefixed(urls.newTab()) })
        expect(router.values.location.pathname).toEqual(prefixed(urls.newTab()))
    })

    it('NEW_INTERNAL_TAB opens a background tab without leaving the current one', async () => {
        // newInternalTab() dispatches this raw action from anywhere in the app
        getContext().store.dispatch({ type: NEW_INTERNAL_TAB, payload: { path: '/insights' } })
        await expectLogic(logic).toFinishAllListeners()
        const background = logic.values.tabs.find((tab) => tab.pathname === prefixed('/insights'))
        expect(background).toMatchObject({ active: false })
        expect(logic.values.activeTab).toMatchObject({ pathname: prefixed('/activity/explore') })
        expect(router.values.location.pathname).toEqual(prefixed('/activity/explore'))
    })

    it('closing the active tab activates its neighbor and navigates there', async () => {
        logic.actions.newTab('/insights')
        await expectLogic(logic).toFinishAllListeners()
        const activeTab = logic.values.activeTab
        expect(activeTab?.pathname).toEqual(prefixed('/insights'))

        logic.actions.removeTab(activeTab!, { source: 'close_button' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.tabs).toHaveLength(1)
        expect(logic.values.activeTab).toMatchObject({ pathname: prefixed('/activity/explore'), active: true })
        expect(router.values.location.pathname).toEqual(prefixed('/activity/explore'))
    })

    it('location changes update the active tab instead of forking a new one', async () => {
        router.actions.push('/dashboard/5?filter=1')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.tabs).toHaveLength(1)
        expect(logic.values.activeTab).toMatchObject({ pathname: prefixed('/dashboard/5'), search: '?filter=1' })
    })

    it('clicking an inactive tab activates it and navigates the router', async () => {
        logic.actions.newTab('/insights')
        await expectLogic(logic).toFinishAllListeners()
        const firstTab = logic.values.tabs.find((tab) => tab.pathname === prefixed('/activity/explore'))!

        logic.actions.clickOnTab(firstTab)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.activeTab?.id).toEqual(firstTab.id)
        expect(router.values.location.pathname).toEqual(prefixed('/activity/explore'))
    })

    describe('fresh desktop windows ("open in new window")', () => {
        // prefixed() needs the team context from initKeaTests, so build the fixture per-test
        const persistedTabs = (): Record<string, any>[] => [
            {
                id: 'pin1',
                pathname: prefixed('/dashboard/1'),
                search: '',
                hash: '',
                title: 'Pinned dashboard',
                iconType: 'dashboard',
                active: false,
                pinned: true,
            },
            {
                id: 'tab2',
                pathname: prefixed('/insights'),
                search: '',
                hash: '',
                title: 'Insights',
                iconType: 'insight',
                active: true,
                pinned: false,
            },
        ]

        const mountFreshWindowAt = (location: string): void => {
            initKeaTests()
            router.actions.push(location)
            logic = sceneTabsLogic.build()
            logic.mount()
        }

        beforeEach(() => {
            window.__POSTHOG_DESKTOP__ = { version: 'test' }
            localStorage.setItem('posthog-desktop-scene-tabs', JSON.stringify(persistedTabs()))
            sessionStorage.setItem('posthog-desktop-fresh-window', '1')
        })

        afterEach(() => {
            delete window.__POSTHOG_DESKTOP__
            sessionStorage.clear()
        })

        it('restores only pinned tabs plus the opened location', () => {
            mountFreshWindowAt('/activity/explore')
            expect(logic.values.tabs).toHaveLength(2)
            expect(logic.values.tabs[0]).toMatchObject({ id: 'pin1', pinned: true, active: false })
            expect(logic.values.tabs[1]).toMatchObject({ pathname: prefixed('/activity/explore'), active: true })
        })

        it('activates a matching pinned tab instead of duplicating it', () => {
            mountFreshWindowAt('/dashboard/1')
            expect(logic.values.tabs).toHaveLength(1)
            expect(logic.values.tabs[0]).toMatchObject({ id: 'pin1', pinned: true, active: true })
        })

        it('does not overwrite the primary window persisted tab set', async () => {
            mountFreshWindowAt('/activity/explore')
            logic.actions.newTab('/persons')
            await expectLogic(logic).toFinishAllListeners()
            expect(JSON.parse(localStorage.getItem('posthog-desktop-scene-tabs')!)).toHaveLength(2)
        })
    })

    it('pinned tabs sort first and reordering respects the pinned group', async () => {
        logic.actions.newTab('/insights')
        logic.actions.newTab('/dashboard/1')
        await expectLogic(logic).toFinishAllListeners()

        const insightsTab = logic.values.tabs.find((tab) => tab.pathname === prefixed('/insights'))!
        logic.actions.pinTab(insightsTab.id)
        expect(logic.values.tabs[0]).toMatchObject({ id: insightsTab.id, pinned: true })

        // Reordering across the pinned boundary is a no-op
        const lastTab = logic.values.tabs[logic.values.tabs.length - 1]
        const before = logic.values.tabs.map((tab) => tab.id)
        logic.actions.reorderTabs(insightsTab.id, lastTab.id)
        expect(logic.values.tabs.map((tab) => tab.id)).toEqual(before)
    })
})
