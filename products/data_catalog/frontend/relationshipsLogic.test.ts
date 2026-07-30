import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { expectLogic } from '~/test/keaTestUtils'

import {
    dataCatalogRelationshipProposalsAcceptCreate,
    dataCatalogRelationshipProposalsList,
    dataCatalogRelationshipProposalsRejectCreate,
} from './generated/api'
import type { DataCatalogRelationshipProposalApi } from './generated/api.schemas'
import { relationshipsLogic } from './relationshipsLogic'

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
    dataCatalogRelationshipProposalsAcceptCreate: jest.fn(),
    dataCatalogRelationshipProposalsRejectCreate: jest.fn(),
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
        ;(api.dataWarehouseViewLinks.list as jest.Mock).mockResolvedValue({ results: joins })
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

    it('loads only the lightweight badge count on mount, not the full proposal payloads', async () => {
        ;(dataCatalogRelationshipProposalsList as jest.Mock).mockResolvedValue({ results: [], count: 3 })
        ;(api.dataWarehouseViewLinks.list as jest.Mock).mockResolvedValue({ results: [] })
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

        expect(rows.find((row) => row.proposalId === 'pending')?.rowStatus).toEqual('pending')
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
