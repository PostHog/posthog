import { expectLogic } from 'kea-test-utils'

import api, { CountedPaginatedResponse } from 'lib/api'

import { initKeaTests } from '~/test/init'
import type { OrganizationMemberType } from '~/types'

import { accountRelatedUsersLogic, PAGE_SIZE } from './accountRelatedUsersLogic'

const buildMember = (overrides: Partial<OrganizationMemberType> = {}): OrganizationMemberType =>
    ({
        id: 'membership-1',
        level: 1,
        user: {
            uuid: 'user-uuid-1',
            distinct_id: 'distinct-1',
            first_name: 'Alex',
            last_name: 'Mercer',
            email: 'alex@example.com',
        },
        ...overrides,
    }) as OrganizationMemberType

const buildResponse = (
    members: OrganizationMemberType[],
    count: number = members.length
): CountedPaginatedResponse<OrganizationMemberType> => ({
    results: members,
    count,
    next: null,
    previous: null,
})

describe('accountRelatedUsersLogic', () => {
    let logic: ReturnType<typeof accountRelatedUsersLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.restoreAllMocks()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('loads the first page of organization members for the account external id', async () => {
        const response = buildResponse([buildMember()], 1)
        const listForOrg = jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(response)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ membersResponse: response })
        expect(listForOrg).toHaveBeenCalledWith('org-uuid', { limit: PAGE_SIZE, offset: 0 })
    })

    it('does not load when the account has no external id', async () => {
        const listForOrg = jest.spyOn(api.organizationMembers, 'listForOrg')

        logic = accountRelatedUsersLogic({ externalId: '' })
        logic.mount()

        await expectLogic(logic).toMatchValues({ membersResponse: null })
        expect(listForOrg).not.toHaveBeenCalled()
    })

    it('reloads the next page when setPage is called', async () => {
        const listForOrg = jest
            .spyOn(api.organizationMembers, 'listForOrg')
            .mockResolvedValue(buildResponse([buildMember()], 7))

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPage(2)

        await expectLogic(logic).toFinishAllListeners()
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', { limit: PAGE_SIZE, offset: PAGE_SIZE })
    })
})
