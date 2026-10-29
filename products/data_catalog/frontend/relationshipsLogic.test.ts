import { router } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import { warehouseViewLinksList } from 'products/data_warehouse/frontend/generated/api'
import { ViewLinkApi } from 'products/data_warehouse/frontend/generated/api.schemas'
import { viewLinkLogic } from 'products/data_warehouse/frontend/shared/logics/viewLinkLogic'

import {
    dataCatalogRelationshipProposalsCreate,
    dataCatalogRelationshipProposalsAcceptCreate,
    dataCatalogRelationshipProposalsList,
    dataCatalogRelationshipProposalsRejectCreate,
} from './generated/api'
import type { DataCatalogRelationshipProposalApi } from './generated/api.schemas'
import { relationshipsLogic } from './relationshipsLogic'
import type { RelationshipsFilters } from './relationshipsLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({ warehouseViewLinksList: jest.fn() }))

jest.mock('lib/api', () => {
    class ApiError extends Error {
        status?: number
        detail: string | null
        constructor(message?: string, status?: number, _headers?: unknown, data?: { detail?: string }) {
            super(message)
            this.status = status
            this.detail = data?.detail ?? null
        }
    }
    return {
        __esModule: true,
        default: { dataWarehouseViewLinks: { list: jest.fn() } },
        ApiConfig: { getCurrentTeamId: jest.fn(() => 1) },
        ApiError,
    }
})

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn(), warning: jest.fn() },
}))

jest.mock('./generated/api', () => ({
    dataCatalogRelationshipProposalsList: jest.fn(),
    dataCatalogRelationshipProposalsCreate: jest.fn(),
    dataCatalogRelationshipProposalsAcceptCreate: jest.fn(),
    dataCatalogRelationshipProposalsRejectCreate: jest.fn(),
}))

jest.mock('lib/utils/deleteWithUndo', () => ({
    deleteWithUndo: jest.fn().mockResolvedValue(undefined),
}))

function buildProposal(overrides: Partial<DataCatalogRelationshipProposalApi>): DataCatalogRelationshipProposalApi {
    return {
        id: 'proposal-1',
        source_table_name: 'events',
        source_table_key: 'person_id',
        joining_table_name: 'persons',
        joining_table_key: 'id',
        field_name: 'person',
        status: 'proposed',
        confidence: 0.9,
        reasoning: 'high match rate',
        rejection_reason: '',
        created_join: null,
        ...overrides,
    } as DataCatalogRelationshipProposalApi
}

describe('relationshipsLogic', () => {
    let logic: ReturnType<typeof relationshipsLogic.build>

    async function mountWith(
        proposals: DataCatalogRelationshipProposalApi[],
        joins: { id: string; source_table_name?: string }[]
    ): Promise<void> {
        ;(dataCatalogRelationshipProposalsList as jest.Mock).mockResolvedValue({
            results: proposals,
            count: proposals.filter((proposal) => proposal.status === 'proposed').length,
        })
        ;(warehouseViewLinksList as jest.Mock).mockResolvedValue({ results: joins })
        initKeaTests()
        logic = relationshipsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPendingCountSuccess'])
        // The full proposal/join payloads load only when the Relationships tab is viewed.
        logic.actions.loadProposals()
        logic.actions.loadJoins()
        await expectLogic(logic).toDispatchActions(['loadProposalsSuccess', 'loadJoinsSuccess'])
    }

    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('prefills a proposal from a BI source and prevents duplicate submissions', async () => {
        await mountWith([], [])
        router.actions.push('/data-catalog', { tab: 'relationships', table: 'events', propose_table: 'events' })
        expect(logic.values.proposalOpen).toBe(true)
        expect(logic.values.proposalDraft.source_table_name).toBe('events')
        logic.actions.setProposalDraft({
            source_table_key: 'account_id',
            joining_table_name: 'accounts',
            joining_table_key: 'id',
            field_name: 'account',
        })
        let finish: (value: unknown) => void = () => {}
        ;(dataCatalogRelationshipProposalsCreate as jest.Mock).mockReturnValue(
            new Promise((resolve) => {
                finish = resolve
            })
        )
        logic.actions.proposeRelationship()
        logic.actions.proposeRelationship()
        expect(dataCatalogRelationshipProposalsCreate).toHaveBeenCalledTimes(1)
        await expectLogic(logic, () => finish({ id: 'proposed' })).toFinishAllListeners()
        expect(logic.values.proposalOpen).toBe(false)
        expect(logic.values.proposing).toBe(false)
        expect(router.values.searchParams.propose_table).toBeUndefined()
    })

    it('loads proposals with the linked table filter before pagination and clears it on general navigation', async () => {
        await mountWith([], [])
        ;(dataCatalogRelationshipProposalsList as jest.Mock).mockImplementation((_project, params) =>
            Promise.resolve({ results: params?.table_name === 'events' ? [buildProposal({})] : [] })
        )
        await expectLogic(logic, () =>
            router.actions.push('/data-catalog', { tab: 'relationships', table: 'events' })
        ).toFinishAllListeners()
        expect(dataCatalogRelationshipProposalsList).toHaveBeenLastCalledWith('1', { table_name: 'events' })
        expect(logic.values.proposals).toHaveLength(1)
        const listCalls = (dataCatalogRelationshipProposalsList as jest.Mock).mock.calls.length
        const joinCalls = (warehouseViewLinksList as jest.Mock).mock.calls.length
        await expectLogic(logic, () =>
            router.actions.push('/data-catalog', {
                tab: 'relationships',
                table: 'events',
                'data-catalog-relationships_order': '-confidence',
            })
        ).toFinishAllListeners()
        expect(dataCatalogRelationshipProposalsList).toHaveBeenCalledTimes(listCalls)
        expect(warehouseViewLinksList).toHaveBeenCalledTimes(joinCalls)
        await expectLogic(logic, () => logic.actions.loadProposals()).toFinishAllListeners()
        expect(dataCatalogRelationshipProposalsList).toHaveBeenLastCalledWith('1', { table_name: 'events' })
        await expectLogic(logic, () =>
            router.actions.push('/data-catalog', { tab: 'relationships' })
        ).toFinishAllListeners()
        expect(dataCatalogRelationshipProposalsList).toHaveBeenLastCalledWith('1', undefined)
        expect(logic.values.proposals).toEqual([])
    })

    it.each(['', 'orders'])('removes the linked table scope when search changes to %j', async (search) => {
        await mountWith([], [])
        const eventsProposal = buildProposal({})
        const ordersProposal = buildProposal({ id: 'orders-proposal', source_table_name: 'orders' })
        ;(dataCatalogRelationshipProposalsList as jest.Mock).mockImplementation((_project, params) =>
            Promise.resolve({
                results: params?.table_name === 'events' ? [eventsProposal] : [eventsProposal, ordersProposal],
            })
        )
        await expectLogic(logic, () =>
            router.actions.push('/data-catalog', { tab: 'relationships', table: 'events' })
        ).toFinishAllListeners()
        logic.actions.setFilters({ status: 'pending' })
        expect(router.values.searchParams.table).toBe('events')

        await expectLogic(logic, () => logic.actions.setFilters({ search })).toFinishAllListeners()

        expect(router.values.searchParams.table).toBeUndefined()
        expect(logic.values.filters).toEqual({ search, status: 'pending' })
        expect(dataCatalogRelationshipProposalsList).toHaveBeenLastCalledWith('1', undefined)
        expect(logic.values.filteredRows.map((row) => row.proposalId)).toContain('orders-proposal')
        await expectLogic(logic, () => logic.actions.loadProposals()).toFinishAllListeners()
        expect(dataCatalogRelationshipProposalsList).toHaveBeenLastCalledWith('1', undefined)
    })

    it('loads only the lightweight badge count on mount, not the full proposal payloads', async () => {
        ;(dataCatalogRelationshipProposalsList as jest.Mock).mockResolvedValue({ results: [], count: 3 })
        ;(warehouseViewLinksList as jest.Mock).mockResolvedValue({ results: [] })
        initKeaTests()
        logic = relationshipsLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadPendingCountSuccess'])
            .toNotHaveDispatchedActions(['loadProposals', 'loadJoins'])
        expect(logic.values.pendingCount).toEqual(3)
        expect(dataCatalogRelationshipProposalsList).toHaveBeenCalledWith('1', { status: 'proposed', limit: 1 })
    })

    it('folds an accepted proposal into its created join and tags it via-catalog', async () => {
        await mountWith(
            [
                buildProposal({
                    id: 'accepted',
                    status: 'accepted',
                    created_join: 'join-1',
                    reviewed_by: { email: 'r@p.com' } as any,
                }),
                buildProposal({ id: 'pending', status: 'proposed' }),
            ],
            [
                { id: 'join-1', source_table_name: 'events' },
                { id: 'join-2', source_table_name: 'manual' },
            ]
        )

        const rows = logic.values.rows
        expect(rows.find((row) => row.proposalId === 'accepted')).toBeUndefined()

        const viaCatalog = rows.find((row) => row.key === 'join-join-1')
        expect(viaCatalog?.viaCatalog).toEqual(true)
        expect(viaCatalog?.rowStatus).toEqual('active')

        const manual = rows.find((row) => row.key === 'join-join-2')
        expect(manual?.viaCatalog).toEqual(false)
        expect(manual?.rowStatus).toEqual('active')
        expect(manual?.joinId).toEqual('join-2')

        const pending = rows.find((row) => row.proposalId === 'pending')
        expect(pending?.rowStatus).toEqual('pending')
        expect(pending?.joinId).toBeNull()
    })

    it.each<[Partial<RelationshipsFilters>, string[]]>([
        [{ status: 'pending' }, ['proposal-pending-1']],
        [{ search: 'customers' }, ['proposal-rejected-1']],
        [{ status: 'active', search: 'persons' }, []],
    ])('narrows filteredRows with filters %o', async (filters, expectedKeys) => {
        await mountWith(
            [
                buildProposal({ id: 'pending-1', status: 'proposed' }),
                buildProposal({
                    id: 'rejected-1',
                    status: 'rejected',
                    source_table_name: 'orders',
                    source_table_key: 'customer_id',
                    joining_table_name: 'customers',
                    joining_table_key: 'id',
                    field_name: 'customer',
                }),
            ],
            [{ id: 'join-1', source_table_name: 'sessions' }]
        )

        logic.actions.setFilters(filters)

        expect(logic.values.filteredRows.map((row) => row.key)).toEqual(expectedKeys)
    })

    it('reloads joins when the shared join modal saves', async () => {
        await mountWith([], [])
        ;(warehouseViewLinksList as jest.Mock).mockClear()

        viewLinkLogic.build().actions.submitViewLinkSuccess({} as any)

        await expectLogic(logic).toDispatchActions(['loadJoins', 'loadJoinsSuccess'])
        expect(warehouseViewLinksList).toHaveBeenCalledTimes(1)
    })

    it('deletes a join against the singular view-link endpoint and reloads', async () => {
        await mountWith([], [{ id: 'join-1', source_table_name: 'events' }])

        logic.actions.deleteJoin({
            id: 'join-1',
            field_name: 'person',
            source_table_name: 'events',
        } as ViewLinkApi)
        await expectLogic(logic).toFinishAllListeners()

        expect(deleteWithUndo).toHaveBeenCalledWith(
            expect.objectContaining({
                endpoint: 'environments/1/warehouse_view_link',
                object: expect.objectContaining({ id: 'join-1' }),
            })
        )
        ;(warehouseViewLinksList as jest.Mock).mockClear()
        ;(deleteWithUndo as jest.Mock).mock.calls[0][0].callback()
        await expectLogic(logic).toDispatchActions(['loadJoins', 'loadJoinsSuccess'])
    })

    it('passes the rejection reason through when rejecting', async () => {
        await mountWith([buildProposal({ id: 'pending', status: 'proposed' })], [])
        ;(dataCatalogRelationshipProposalsRejectCreate as jest.Mock).mockResolvedValue(
            buildProposal({ status: 'rejected' })
        )

        logic.actions.rejectProposal('pending', 'wrong join')
        await expectLogic(logic).toFinishAllListeners()

        expect(dataCatalogRelationshipProposalsRejectCreate).toHaveBeenCalledWith('1', 'pending', {
            rejection_reason: 'wrong join',
        })
    })

    it('surfaces the error and clears loading when accept fails', async () => {
        await mountWith([buildProposal({ id: 'pending', status: 'proposed' })], [])
        ;(dataCatalogRelationshipProposalsAcceptCreate as jest.Mock).mockRejectedValue(new Error('probe failed'))

        logic.actions.acceptProposal('pending')
        await expectLogic(logic).toFinishAllListeners()

        expect(lemonToast.error).toHaveBeenCalled()
        expect(logic.values.actionsInFlight.pending).toEqual(false)
    })
})
