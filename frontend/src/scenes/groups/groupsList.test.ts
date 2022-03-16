import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import { urls } from 'scenes/urls'
import { initKeaTests } from '~/test/init'
import { groupsListLogic } from './groupsListLogic'
import { useMocks } from '~/mocks/jest'

describe('groupsListLogic', () => {
    let logic: ReturnType<typeof groupsListLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/${MOCK_TEAM_ID}/groups/': { result: ['result from api'], next: null, previous: null },
            },
        })
        initKeaTests()
        logic = groupsListLogic()
        logic.mount()
    })

    beforeEach(() => {
        jest.spyOn(logic.selectors, 'groupsEnabled').mockReturnValue(true)
    })

    it('sets the tab and loads groups upon tab change', async () => {
        router.actions.push(urls.groups('0'))
        await expectLogic(logic)
            .toDispatchActions(['setTab'])
            .toMatchValues({ currentTab: '0' })
            .toDispatchActions(['loadGroups'])
    })

    it('when moving from groups to persons, the tab sets as expected, but only once', async () => {
        router.actions.push(urls.groups('0'))
        await expectLogic(logic)
            .toDispatchActions(['setTab'])
            .toMatchValues({ currentTab: '0' })
            .toDispatchActions(['loadGroups'])

        router.actions.push(urls.persons())
        await expectLogic(logic).toDispatchActions(['setTab']).toMatchValues({ currentTab: '-1' })

        router.actions.push(urls.persons() + '?q=test')
        await expectLogic(logic).toNotHaveDispatchedActions(['setTab'])
    })
})
