import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { defaultAPIMocks, mockAPI, MOCK_TEAM_ID } from 'lib/api.mock'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { groupsListLogic } from './groupsListLogic'

jest.mock('lib/api')

describe('groupsListLogic', () => {
    let logic: ReturnType<typeof groupsListLogic.build>

    mockAPI(async (url) => {
        const { pathname } = url
        if (`api/projects/${MOCK_TEAM_ID}/groups/?group_type_index=0` === pathname) {
            return { result: ['result from api'], next_url: null, previous_url: null }
        }
        return defaultAPIMocks(url)
    })

    beforeEach(async () => {
        initKeaTests()
        groupsModel.mount()
        teamLogic.mount()
        logic = groupsListLogic()
        logic.mount()
    })

    it('sets the tab and loads groups upon tab change', async () => {
        router.actions.push(urls.groups('0'))
        await expectLogic(logic)
            .toDispatchActions(['setTab'])
            .toMatchValues({ currentTab: '0' })
            .toDispatchActions(['loadGroups'])
    })
})
