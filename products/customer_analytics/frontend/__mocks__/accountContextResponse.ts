import type { EndpointRunResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

import { CONTEXT_COLUMNS } from '../components/Accounts/accountContextData'

export function accountContextResponse(rows: Record<string, unknown>[]): EndpointRunResponseApi {
    return {
        name: 'account-context',
        columns: [...CONTEXT_COLUMNS],
        results: rows.map((row) => CONTEXT_COLUMNS.map((column) => row[column] ?? null)),
    }
}
