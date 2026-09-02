import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { SessionRecordingSidebarTab } from '~/types'

import { playerSidebarLogic } from './playerSidebarLogic'

describe('playerSidebarLogic', () => {
    let logic: ReturnType<typeof playerSidebarLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = playerSidebarLogic()
        logic.mount()
    })

    it('follows the host default until the viewer picks a tab, then keeps their pick', async () => {
        await expectLogic(logic).toMatchValues({ activeTab: SessionRecordingSidebarTab.INSPECTOR })

        await expectLogic(logic, () => {
            logic.actions.setDefaultTab(SessionRecordingSidebarTab.OVERVIEW)
        }).toMatchValues({ activeTab: SessionRecordingSidebarTab.OVERVIEW })

        await expectLogic(logic, () => {
            logic.actions.setTab(SessionRecordingSidebarTab.NETWORK_WATERFALL)
        }).toMatchValues({ activeTab: SessionRecordingSidebarTab.NETWORK_WATERFALL })

        // Hosts re-announce their default on every remount, so a default arriving after a pick must
        // not drag the viewer off the tab they're on.
        await expectLogic(logic, () => {
            logic.actions.setDefaultTab(SessionRecordingSidebarTab.OVERVIEW)
        }).toMatchValues({ activeTab: SessionRecordingSidebarTab.NETWORK_WATERFALL })
    })

    it("still reads a bare tab from an older link, as the viewer's pick", async () => {
        logic.actions.setDefaultTab(SessionRecordingSidebarTab.OVERVIEW)
        router.actions.push('/replay', {
            sessionRecordingId: 'abc',
            tab: SessionRecordingSidebarTab.OVERVIEW,
        })
        await expectLogic(logic).toMatchValues({ selectedTab: SessionRecordingSidebarTab.OVERVIEW })

        // Only sticks because the URL was taken as a pick. Had it been waved through for already
        // matching the default, the tab would follow the host away instead of the link.
        await expectLogic(logic, () => {
            logic.actions.setDefaultTab(SessionRecordingSidebarTab.INSPECTOR)
        }).toMatchValues({ activeTab: SessionRecordingSidebarTab.OVERVIEW })
    })

    it('honors a tab from the URL when no recording id is in the URL', async () => {
        // On /replay/home the first recording autoplays without its id ever reaching the URL, so a
        // refresh has to restore the tab without one to key off. Remounting with the tab already in
        // the URL is what that refresh looks like.
        logic.unmount()
        router.actions.push('/replay/home', { sidebarTab: SessionRecordingSidebarTab.NETWORK_WATERFALL })
        logic = playerSidebarLogic()
        logic.mount()

        await expectLogic(logic).toMatchValues({ activeTab: SessionRecordingSidebarTab.NETWORK_WATERFALL })
    })

    it('leaves a bare tab alone when another scene owns it', async () => {
        // Two sidebar tab values are also tab values elsewhere ('overview' on a group page,
        // 'sessions' in activity), and this logic matches on '*', so it sees those URLs too.
        router.actions.push('/groups/0/abc', { tab: SessionRecordingSidebarTab.OVERVIEW })

        await expectLogic(logic).toMatchValues({
            selectedTab: null,
            activeTab: SessionRecordingSidebarTab.INSPECTOR,
        })
    })

    it("leaves a host scene's own tab untouched when the viewer picks a sidebar tab", () => {
        // The experiment view keeps its active tab in `tab` and clamps a value it doesn't know back
        // to its default, so writing the sidebar's pick there drops the viewer out of the recording.
        router.actions.push('/experiments/123', { tab: 'recordings' })

        logic.actions.setTab(SessionRecordingSidebarTab.NETWORK_WATERFALL)

        expect(router.values.searchParams).toEqual({
            tab: 'recordings',
            sidebarTab: SessionRecordingSidebarTab.NETWORK_WATERFALL,
        })
    })

    it('keeps the host default out of the URL', () => {
        logic.actions.setDefaultTab(SessionRecordingSidebarTab.OVERVIEW)
        expect(router.values.searchParams).not.toHaveProperty('sidebarTab')

        // The viewer's own pick is theirs to share, so that one does belong in the URL.
        logic.actions.setTab(SessionRecordingSidebarTab.OVERVIEW)
        expect(router.values.searchParams).toHaveProperty('sidebarTab', SessionRecordingSidebarTab.OVERVIEW)
    })
})
