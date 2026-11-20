import type { LoginKindEnumApi } from 'products/data_warehouse/frontend/generated/api.schemas'

export interface WarehouseLoginActions {
    canRotate: boolean
    canDisable: boolean
    canDelete: boolean
}

// Only a project login belongs to PostHog's console. The root login and any other login are listed read-only.
export function warehouseLoginActions(kind: LoginKindEnumApi): WarehouseLoginActions {
    const isProjectLogin = kind === 'project_reader' || kind === 'project_user'
    return { canRotate: isProjectLogin, canDisable: isProjectLogin, canDelete: isProjectLogin }
}
