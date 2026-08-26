import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api, { CountedPaginatedResponse } from 'lib/api'
import { OrganizationMembershipLevel } from 'lib/constants'

import { initKeaTests } from '~/test/init'
import { OrganizationMemberType, Region } from '~/types'

import { accountRelatedUsersLogic, PAGE_SIZE } from './accountRelatedUsersLogic'

const buildMember = (overrides: Partial<OrganizationMemberType> = {}): OrganizationMemberType =>
    ({
        id: 'membership-1',
        level: 1,
        user: {
            id: 1,
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

    it('loads the first page of US organization members for the account external id', async () => {
        const member = buildMember()
        const response = buildResponse([member], 1)
        const listForOrg = jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(response)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ membersResponse: { ...response, results: [{ ...member, region: Region.US }] } })
        expect(listForOrg).toHaveBeenCalledWith('org-uuid', { limit: 20, offset: 0 })
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
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', { limit: 20, offset: 20 })
    })

    it('resets to the first page and sends the user search to the API', async () => {
        const listForOrg = jest
            .spyOn(api.organizationMembers, 'listForOrg')
            .mockResolvedValue(buildResponse([buildMember()], PAGE_SIZE + 1))

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearchTerm('Ada')

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ page: 1, searchTerm: 'Ada' })
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', { limit: PAGE_SIZE, offset: 0, search: 'Ada' })
    })

    it('does not load EU members when a US user search has no matches', async () => {
        const listForOrg = jest
            .spyOn(api.organizationMembers, 'listForOrg')
            .mockResolvedValueOnce(buildResponse([buildMember()]))
            .mockResolvedValueOnce(buildResponse([]))
        const query = jest.spyOn(api, 'query')

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearchTerm('Nobody')

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ membersResponse: buildResponse([]) })
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', { limit: PAGE_SIZE, offset: 0, search: 'Nobody' })
        expect(query).not.toHaveBeenCalled()
    })

    const buildEuRow = (
        n: number,
        level: OrganizationMembershipLevel = OrganizationMembershipLevel.Member
    ): unknown[] => [100 + n, `eu-m-${n}`, level, `First${n}`, `Last${n}`, `eu${n}@example.com`, `did-${n}`]

    it('falls back to the EU warehouse view when the org has no local members', async () => {
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(buildResponse([], 0))
        const query = jest
            .spyOn(api, 'query')
            .mockResolvedValue({ results: [buildEuRow(1, OrganizationMembershipLevel.Admin), buildEuRow(2)] } as any)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners()
        expect(query).toHaveBeenCalledTimes(1)
        expect(logic.values.membersResponse).toMatchObject({
            count: 2,
            results: [
                {
                    id: 'eu-m-1',
                    level: OrganizationMembershipLevel.Admin,
                    user: { id: 101, first_name: 'First1', email: 'eu1@example.com', distinct_id: 'did-1' },
                    region: Region.EU,
                },
                {
                    id: 'eu-m-2',
                    level: OrganizationMembershipLevel.Member,
                    user: { id: 102, first_name: 'First2', email: 'eu2@example.com', distinct_id: 'did-2' },
                    region: Region.EU,
                },
            ],
        })
    })

    it('paginates cached EU members client-side without refetching', async () => {
        const listForOrg = jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(buildResponse([], 0))
        const query = jest
            .spyOn(api, 'query')
            .mockResolvedValue({ results: Array.from({ length: PAGE_SIZE + 2 }, (_, i) => buildEuRow(i + 1)) } as any)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPage(2)

        await expectLogic(logic).toFinishAllListeners()
        expect(listForOrg).toHaveBeenCalledTimes(1)
        expect(query).toHaveBeenCalledTimes(1)
        expect(logic.values.membersResponse).toMatchObject({
            count: PAGE_SIZE + 2,
            results: [{ id: `eu-m-${PAGE_SIZE + 1}` }, { id: `eu-m-${PAGE_SIZE + 2}` }],
        })
    })

    it('filters cached EU members by name without loading them again', async () => {
        const listForOrg = jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(buildResponse([], 0))
        const query = jest.spyOn(api, 'query').mockResolvedValue({ results: [buildEuRow(1), buildEuRow(2)] } as any)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSearchTerm('First2')

        await expectLogic(logic).toFinishAllListeners()
        expect(listForOrg).toHaveBeenCalledTimes(1)
        expect(query).toHaveBeenCalledTimes(1)
        expect(logic.values.membersResponse).toMatchObject({ count: 1, results: [{ id: 'eu-m-2' }] })
    })

    it('degrades to the empty response when the EU view does not exist', async () => {
        const emptyResponse = buildResponse([], 0)
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(emptyResponse)
        jest.spyOn(api, 'query').mockRejectedValue(new Error('Unknown table eu_org_members'))
        const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ membersResponse: emptyResponse })
        expect(captureException).not.toHaveBeenCalled()
    })
})
