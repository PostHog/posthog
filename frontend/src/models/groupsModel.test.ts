import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { groupsModel } from '~/models/groupsModel'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, TeamType } from '~/types'

const ORGANIZATION_WITH_GROUPS = {
    ...MOCK_DEFAULT_ORGANIZATION,
    available_product_features: [{ key: AvailableFeature.GROUP_ANALYTICS, name: AvailableFeature.GROUP_ANALYTICS }],
}

describe('groupsModel', () => {
    let groupTypesRequest: jest.Mock

    beforeEach(() => {
        groupTypesRequest = jest.fn(() => [200, []])
        useMocks({ get: { '/api/projects/:team_id/groups_types': groupTypesRequest } })
    })

    afterEach(() => {
        groupsModel.unmount()
    })

    it.each([
        {
            name: 'uses app context group types without a request',
            team: MOCK_DEFAULT_TEAM,
            expectedRequests: 0,
            expectedGroupTypeCount: MOCK_DEFAULT_TEAM.group_types.length,
        },
        {
            name: 'loads group types once when the app context has none',
            team: { ...MOCK_DEFAULT_TEAM, group_types: undefined } as unknown as TeamType,
            expectedRequests: 1,
            expectedGroupTypeCount: 0,
        },
    ])('on mount with groups enabled, $name', async ({ team, expectedRequests, expectedGroupTypeCount }) => {
        initKeaTests(true, team, undefined, ORGANIZATION_WITH_GROUPS)
        groupsModel.mount()

        await expectLogic(groupsModel).toFinishAllListeners()

        expect(groupsModel.values.groupsEnabled).toBe(true)
        expect(groupTypesRequest).toHaveBeenCalledTimes(expectedRequests)
        expect(groupsModel.values.groupTypes.size).toBe(expectedGroupTypeCount)
    })

    it('loads group types when groups become available after mount', async () => {
        initKeaTests(true, MOCK_DEFAULT_TEAM, undefined, MOCK_DEFAULT_ORGANIZATION)
        groupsModel.mount()
        await expectLogic(groupsModel).toFinishAllListeners()
        expect(groupTypesRequest).not.toHaveBeenCalled()

        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, organization: ORGANIZATION_WITH_GROUPS })
        await expectLogic(groupsModel).toFinishAllListeners()

        expect(groupTypesRequest).toHaveBeenCalledTimes(1)
    })
})
