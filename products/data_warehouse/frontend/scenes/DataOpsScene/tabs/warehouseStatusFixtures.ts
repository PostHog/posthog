import type {
    WarehouseStatusResponseApi,
    WarehouseTrinoStatusApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

export function warehouseStatusFixture(
    overrides: Partial<WarehouseStatusResponseApi> = {}
): WarehouseStatusResponseApi {
    return {
        org_id: 'org-1',
        state: 'ready',
        status_message: '',
        s3_state: 'ready',
        metadata_store_state: 'ready',
        identity_state: 'ready',
        secrets_state: 'ready',
        ready_at: '2026-08-01T12:00:00Z',
        failed_at: null,
        connection: null,
        trino: null,
        has_backfill: false,
        table_suffix: null,
        team_onboarded: true,
        schema_name: 'analytics',
        ...overrides,
    }
}

export function trinoStatusFixture(overrides: Partial<WarehouseTrinoStatusApi> = {}): WarehouseTrinoStatusApi {
    return { state: 'ready', ready_at: '2026-09-01T12:00:00Z', connection: null, ...overrides }
}
