import type { LoginKindEnumApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export interface WarehouseLoginActions {
    canRotate: boolean
    canDisable: boolean
    canDelete: boolean
    canReset: boolean
}

// Project logins belong to PostHog's console: they can be rotated, switched off and deleted.
// The root login only has its password reset. Any other login is listed read-only.
export function warehouseLoginActions(kind: LoginKindEnumApi): WarehouseLoginActions {
    const isProjectLogin = kind === 'project_reader' || kind === 'project_user'
    return {
        canRotate: isProjectLogin,
        canDisable: isProjectLogin,
        canDelete: isProjectLogin,
        canReset: kind === 'root',
    }
}
