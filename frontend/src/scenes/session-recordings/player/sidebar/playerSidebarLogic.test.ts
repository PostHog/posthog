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

    it('records a tab from the URL as the pick, even when a host default already matches it', async () => {
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

    it('keeps the host default out of the URL', () => {
        logic.actions.setDefaultTab(SessionRecordingSidebarTab.OVERVIEW)
        expect(router.values.searchParams).not.toHaveProperty('sidebarTab')

        // The viewer's own pick is theirs to share, so that one does belong in the URL.
        logic.actions.setTab(SessionRecordingSidebarTab.OVERVIEW)
        expect(router.values.searchParams).toHaveProperty('sidebarTab', SessionRecordingSidebarTab.OVERVIEW)
    })

    it("leaves the host scene's own tab param alone", () => {
        // A scene that embeds the player and reads `tab` itself, such as the experiment recordings
        // tab, used to lose its value to the sidebar here. It then resolved the sidebar tab it found
        // back to its own default, throwing the viewer out of the recording they were watching.
        router.actions.push('/experiments/123', { tab: 'recordings', sessionRecordingId: 'abc' })

        logic.actions.setTab(SessionRecordingSidebarTab.INSPECTOR)

        expect(router.values.searchParams).toEqual({
            tab: 'recordings',
            sessionRecordingId: 'abc',
            sidebarTab: SessionRecordingSidebarTab.INSPECTOR,
        })
    })

    it('reads a sidebar tab shared under the pre-namespace param and rewrites it namespaced', async () => {
        router.actions.push('/replay', {
            sessionRecordingId: 'abc',
            tab: SessionRecordingSidebarTab.NETWORK_WATERFALL,
        })

        await expectLogic(logic).toMatchValues({ selectedTab: SessionRecordingSidebarTab.NETWORK_WATERFALL })
        // Taking the old param as a pick re-dispatches it, which rewrites the URL under the
        // namespaced key so the link stops carrying a `tab` that a host scene would try to read.
        expect(router.values.searchParams).toEqual({
            sessionRecordingId: 'abc',
            sidebarTab: SessionRecordingSidebarTab.NETWORK_WATERFALL,
        })
    })
})
