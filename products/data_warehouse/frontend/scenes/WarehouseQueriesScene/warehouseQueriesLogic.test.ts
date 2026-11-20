import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'
import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { OrganizationMembershipLevel } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import {
    managedWarehouseConsoleQueriesCancelCreate,
    managedWarehouseConsoleQueriesRetrieve,
} from 'products/data_warehouse/frontend/generated/api'
import type {
    ManagedWarehouseTrinoMonitoringSnapshotResponseApi,
    QueryHistoryRowApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

import { canCancelQuery, warehouseQueriesLogic } from './warehouseQueriesLogic'

jest.mock('products/data_warehouse/frontend/generated/api', () => ({
    dataWarehouseWarehouseStatusRetrieve: jest.fn().mockResolvedValue(null),
    dataWarehouseManagedWarehouseTrinoMonitoringRetrieve: jest.fn().mockResolvedValue(null),
    managedWarehouseConsoleQueriesRetrieve: jest.fn(),
    managedWarehouseConsoleQueriesCancelCreate: jest.fn(),
}))
jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}))

const mockHistory = managedWarehouseConsoleQueriesRetrieve as jest.MockedFunction<
    typeof managedWarehouseConsoleQueriesRetrieve
>
const mockCancel = managedWarehouseConsoleQueriesCancelCreate as jest.MockedFunction<
    typeof managedWarehouseConsoleQueriesCancelCreate
>

function historyRow(id: number): QueryHistoryRowApi {
    return {
        id,
        query_id: `q${id}`,
        principal: 'p',
        principal_label: 'Login',
        team_id: null,
        source: 's',
        source_label: 'Source',
        state: 'FINISHED',
        error_code: null,
        error_type: null,
        created_at: '2026-11-19T10:00:00Z',
        completed_at: '2026-11-19T10:00:01Z',
        elapsed_ms: 1000,
        queued_ms: 0,
        logical_bytes_scanned: 0,
        billable: true,
        billable_bytes: 0,
        cpu_seconds: null,
        query: 'SELECT ?',
        estimated_cost_usd: '0',
    }
}

function snapshot(users: string[]): ManagedWarehouseTrinoMonitoringSnapshotResponseApi {
    return {
        schema_version: 1,
        org_id: 'org',
        as_of: '2026-11-19T10:00:00Z',
        trino: { state: 'ready', ready_at: null, failed_at: null },
        available: true,
        limits: { max_running_queries: 10, max_queued_queries: 50 },
        totals: {
            in_flight: users.length,
            running: users.length,
            queued: 0,
            blocked: 0,
            longest_running_ms: 0,
            physical_input_bytes: 0,
        },
        queries: users.map((user, index) => ({
            query_id: `run${index}`,
            state: 'running',
            user,
            source: '',
            query: 'SELECT ?',
            created_at: null,
            elapsed_ms: 1000,
            queued_ms: 0,
            cpu_ms: 0,
            physical_input_bytes: 0,
            peak_memory_bytes: 0,
            processed_input_rows: 0,
            progress_percentage: null,
            blocked: false,
        })),
        queries_truncated: false,
    }
}

function mountAs(level: OrganizationMembershipLevel): ReturnType<typeof warehouseQueriesLogic.build> {
    initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
        ...MOCK_DEFAULT_ORGANIZATION,
        membership_level: level,
    })
    userLogic.mount()
    const logic = warehouseQueriesLogic()
    logic.mount()
    return logic
}

describe('canCancelQuery', () => {
    it.each([
        ['an admin cancels any login', true, 2, 'someone-else', true],
        ['a member cancels their own SQL editor login', false, 2, 'posthog:sql-editor:team:1:user:2', true],
        ['a member cancels their own login from another project', false, 2, 'posthog:sql-editor:team:77:user:2', true],
        ['a member cannot cancel another person', false, 2, 'posthog:sql-editor:team:1:user:3', false],
        [
            'a member cannot cancel a user id that only starts with theirs',
            false,
            2,
            'posthog:sql-editor:team:1:user:22',
            false,
        ],
        ['a member cannot cancel a non SQL editor login', false, 2, 'hl_metabase', false],
        ['a member without a user id cannot cancel', false, null, 'posthog:sql-editor:team:1:user:2', false],
    ])('%s', (_name, isAdmin, userId, queryPrincipal, expected) => {
        expect(canCancelQuery(isAdmin, userId, queryPrincipal)).toBe(expected)
    })
})

describe('warehouseQueriesLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('lets a member cancel only their own SQL editor queries', async () => {
        const logic = mountAs(OrganizationMembershipLevel.Member)
        const own = `posthog:sql-editor:team:${MOCK_DEFAULT_TEAM.id + 1}:user:${userLogic.values.user?.id}`
        logic.actions.loadRunningSuccess(snapshot([own, 'trino-login']))

        expect(logic.values.runningRows.map((row) => [row.query_id, row.canCancel, row.loginLabel])).toEqual([
            ['run0', true, 'You'],
            ['run1', false, 'trino-login'],
        ])

        mockCancel.mockResolvedValue({ status: 'cancel_requested' })
        logic.actions.requestCancel('run0')
        await expectLogic(logic, () => logic.actions.confirmCancel('run0')).toDispatchActions([
            'confirmCancel',
            'cancelSettled',
        ])
        expect(mockCancel).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'run0', { principal: own })
    })

    it('lets an admin cancel any query without sending a principal', async () => {
        const logic = mountAs(OrganizationMembershipLevel.Admin)
        logic.actions.loadRunningSuccess(snapshot(['trino-login']))
        expect(logic.values.runningRows[0].canCancel).toBe(true)

        mockCancel.mockResolvedValue({ status: 'cancel_requested' })
        await expectLogic(logic, () => logic.actions.confirmCancel('run0')).toDispatchActions(['cancelSettled'])
        expect(mockCancel).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), 'run0', undefined)
    })

    it('treats a 404 on cancel as a finished query', async () => {
        const logic = mountAs(OrganizationMembershipLevel.Admin)
        logic.actions.loadRunningSuccess(snapshot(['trino-login']))
        mockCancel.mockRejectedValue({ status: 404 })

        await expectLogic(logic, () => logic.actions.confirmCancel('run0')).toDispatchActions(['cancelSettled'])
        expect(logic.values.cancelingIds).toEqual([])
    })

    it('appends the next history page and keeps the filter options of every page', async () => {
        const logic = mountAs(OrganizationMembershipLevel.Admin)
        mockHistory
            .mockResolvedValueOnce({ queries: [historyRow(3), historyRow(2)], next_cursor: 'c2' })
            .mockResolvedValueOnce({ queries: [historyRow(1)], next_cursor: null })

        await expectLogic(logic, () => logic.actions.loadHistory()).toFinishAllListeners()
        expect(logic.values.hasMoreHistory).toBe(true)

        await expectLogic(logic, () => logic.actions.loadMoreHistory()).toFinishAllListeners()
        expect(logic.values.historyRows.map((row) => row.id)).toEqual([3, 2, 1])
        expect(logic.values.hasMoreHistory).toBe(false)
        expect(mockHistory.mock.calls[1][1]).toMatchObject({ cursor: 'c2' })
        expect(logic.values.sourceOptions).toEqual([{ value: 's', label: 'Source' }])
    })
})
