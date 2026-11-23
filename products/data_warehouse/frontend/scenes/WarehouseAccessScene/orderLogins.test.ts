import type { WarehouseLoginApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { orderLogins } from './orderLogins'

const login = (username: string, kind: WarehouseLoginApi['kind'], team_id: number | null): WarehouseLoginApi => ({
    username,
    kind,
    team_id,
    scope_label: '',
    disabled: false,
    created_at: null,
    updated_at: null,
    queries_30d: 0,
    billable_bytes_30d: 0,
})

describe('orderLogins', () => {
    it('puts root first, project logins by project and access, then other logins', () => {
        const ordered = orderLogins([
            login('hl_dbt_rw', 'other', null),
            login('posthog_team_2', 'project_reader', 2),
            login('posthog_team_1_rw', 'project_user', 1),
            login('root', 'root', null),
            login('posthog_team_1', 'project_reader', 1),
        ])
        expect(ordered.map((row) => row.username)).toEqual([
            'root',
            'posthog_team_1',
            'posthog_team_1_rw',
            'posthog_team_2',
            'hl_dbt_rw',
        ])
    })
})
