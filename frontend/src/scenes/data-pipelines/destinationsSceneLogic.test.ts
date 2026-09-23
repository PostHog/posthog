import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { DestinationsSceneTab, destinationsSceneLogic } from './destinationsSceneLogic'

describe('destinationsSceneLogic', () => {
    let logic: ReturnType<typeof destinationsSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
        logic = destinationsSceneLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each<[string | undefined, DestinationsSceneTab]>([
        ['batch', 'batch'],
        ['notifications', 'notifications'],
        ['history', 'history'],
        // `?tab=all` is what bookmarks from the single-list version of the scene carry.
        ['all', 'realtime'],
        [undefined, 'realtime'],
    ])('opens the "%s" URL tab as %s', async (tab, expected) => {
        router.actions.push(urls.destinations(), tab ? { tab } : {})

        await expectLogic(logic).toMatchValues({ activeTab: expected })
    })

    it('writes every tab except the default one to the URL', async () => {
        router.actions.push(urls.destinations())

        logic.actions.setActiveTab('batch')
        await expectLogic(logic).toMatchValues({ activeTab: 'batch' })
        expect(router.values.searchParams.tab).toBe('batch')

        logic.actions.setActiveTab('realtime')
        await expectLogic(logic).toMatchValues({ activeTab: 'realtime' })
        expect(router.values.searchParams.tab).toBeUndefined()
    })
})
