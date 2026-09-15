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
        last_login: '2026-01-02T03:04:05Z',
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

    it('sends the sort as the backend ordering param and resets to the first page', async () => {
        const listForOrg = jest
            .spyOn(api.organizationMembers, 'listForOrg')
            .mockResolvedValue(buildResponse([buildMember()], PAGE_SIZE + 1))

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setPage(2)
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSorting({ columnKey: 'last_login', order: -1 })

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ page: 1 })
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', {
            limit: PAGE_SIZE,
            offset: 0,
            ordering: '-last_login',
        })

        logic.actions.setSorting(null)

        await expectLogic(logic).toFinishAllListeners()
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', { limit: PAGE_SIZE, offset: 0 })
    })

    it('sends selected access levels as a comma-separated levels param', async () => {
        const listForOrg = jest
            .spyOn(api.organizationMembers, 'listForOrg')
            .mockResolvedValueOnce(buildResponse([buildMember()]))
            .mockResolvedValueOnce(buildResponse([]))
        const query = jest.spyOn(api, 'query')

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setLevels([OrganizationMembershipLevel.Owner, OrganizationMembershipLevel.Admin])

        await expectLogic(logic).toFinishAllListeners().toMatchValues({ page: 1 })
        expect(listForOrg).toHaveBeenLastCalledWith('org-uuid', { limit: PAGE_SIZE, offset: 0, levels: '15,8' })
        // The org has US members, so an empty filtered page is "no match", not a reason to look in the EU view.
        expect(query).not.toHaveBeenCalled()
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
        level: OrganizationMembershipLevel = OrganizationMembershipLevel.Member,
        lastLogin: string | null = null
    ): unknown[] => [100 + n, `eu-m-${n}`, level, `First${n}`, `Last${n}`, `eu${n}@example.com`, `did-${n}`, lastLogin]

    it('falls back to the EU warehouse view when the org has no local members', async () => {
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(buildResponse([], 0))
        const query = jest.spyOn(api, 'query').mockResolvedValue({
            results: [buildEuRow(1, OrganizationMembershipLevel.Admin, '2026-01-02T03:04:05Z'), buildEuRow(2)],
        } as any)

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
                    last_login: '2026-01-02T03:04:05Z',
                    region: Region.EU,
                },
                {
                    id: 'eu-m-2',
                    level: OrganizationMembershipLevel.Member,
                    user: { id: 102, first_name: 'First2', email: 'eu2@example.com', distinct_id: 'did-2' },
                    last_login: null,
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

    it('applies a filter set before the first load finishes to EU members', async () => {
        jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(buildResponse([], 0))
        const query = jest.spyOn(api, 'query').mockResolvedValue({
            results: [
                buildEuRow(1, OrganizationMembershipLevel.Member),
                buildEuRow(2, OrganizationMembershipLevel.Admin),
            ],
        } as any)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        logic.actions.setLevels([OrganizationMembershipLevel.Admin])

        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.membersResponse).toMatchObject({ count: 1, results: [{ id: 'eu-m-2' }] })

        logic.actions.setLevels([])

        await expectLogic(logic).toFinishAllListeners()
        expect(query).toHaveBeenCalledTimes(1)
        expect(logic.values.membersResponse).toMatchObject({ count: 2 })
    })

    it('sorts and filters cached EU members client-side without refetching', async () => {
        const listForOrg = jest.spyOn(api.organizationMembers, 'listForOrg').mockResolvedValue(buildResponse([], 0))
        const query = jest.spyOn(api, 'query').mockResolvedValue({
            results: [
                buildEuRow(1, OrganizationMembershipLevel.Member, '2026-03-01T00:00:00Z'),
                buildEuRow(2, OrganizationMembershipLevel.Owner, null),
                buildEuRow(3, OrganizationMembershipLevel.Admin, '2026-01-01T00:00:00Z'),
            ],
        } as any)

        logic = accountRelatedUsersLogic({ externalId: 'org-uuid' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.setSorting({ columnKey: 'level', order: -1 })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.membersResponse).toMatchObject({
            results: [{ id: 'eu-m-2' }, { id: 'eu-m-3' }, { id: 'eu-m-1' }],
        })

        logic.actions.setSorting({ columnKey: 'last_login', order: -1 })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.membersResponse).toMatchObject({
            results: [{ id: 'eu-m-1' }, { id: 'eu-m-3' }, { id: 'eu-m-2' }],
        })

        logic.actions.setSorting({ columnKey: 'last_login', order: 1 })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.membersResponse).toMatchObject({
            results: [{ id: 'eu-m-2' }, { id: 'eu-m-3' }, { id: 'eu-m-1' }],
        })

        logic.actions.setLevels([OrganizationMembershipLevel.Admin])
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.membersResponse).toMatchObject({ count: 1, results: [{ id: 'eu-m-3' }] })

        expect(listForOrg).toHaveBeenCalledTimes(1)
        expect(query).toHaveBeenCalledTimes(1)
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
