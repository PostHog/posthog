import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { scenesTabsLogic } from './scenesTabsLogic'

describe('scenesTabsLogic', () => {
    beforeEach(() => {
        initKeaTests()
        scenesTabsLogic.mount()
    })

    test.each([
        ['/support', 'overview'],
        ['/support/tickets', 'tickets'],
        ['/support/tickets/abc', 'tickets'],
        ['/support/settings', 'settings'],
    ])('%s activates the %s tab', async (url, tab) => {
        router.actions.push(url)
        await expectLogic(scenesTabsLogic).toMatchValues({ activeTab: tab })
    })
})
