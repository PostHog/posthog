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
        expect(router.values.searchParams).not.toHaveProperty('tab')

        // The viewer's own pick is theirs to share, so that one does belong in the URL.
        logic.actions.setTab(SessionRecordingSidebarTab.OVERVIEW)
        expect(router.values.searchParams).toHaveProperty('tab', SessionRecordingSidebarTab.OVERVIEW)
    })
})
