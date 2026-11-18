import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { playlistFiltersLogic } from 'scenes/session-recordings/playlist/playlistFiltersLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'
import { ReplayTabs } from '~/types'

describe('playlistFiltersLogic', () => {
    let logic: ReturnType<typeof playlistFiltersLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = playlistFiltersLogic()
        logic.mount()
    })

    it.each([
        ['saved', 'saved'],
        ['templates', 'templates'],
        ['unknown', 'filters'],
    ])('filtersTab=%s in the URL selects the %s tab', async (filtersTab, expected) => {
        router.actions.push(urls.replay(ReplayTabs.Home), { filtersTab })

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.activeFilterTab).toBe(expected)
    })
})
