import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { ManagedWarehouseReadinessStateEnumApi } from 'products/data_warehouse/frontend/generated/api.schemas'

// Keep labels and colors aligned for each warehouse dataset status.

export const STATUS_LABELS: Record<ManagedWarehouseReadinessStateEnumApi, string> = {
    not_configured: 'Not configured',
    waiting: 'Waiting',
    backfilling: 'Backfilling',
    up_to_date: 'Up to date',
    needs_attention: 'Needs attention',
}

export const STATUS_TAG_TYPES: Record<ManagedWarehouseReadinessStateEnumApi, LemonTagType> = {
    not_configured: 'muted',
    waiting: 'warning',
    backfilling: 'primary',
    up_to_date: 'success',
    needs_attention: 'danger',
}

export function StatusTag({ readinessState }: { readinessState: ManagedWarehouseReadinessStateEnumApi }): JSX.Element {
    return <LemonTag type={STATUS_TAG_TYPES[readinessState]}>{STATUS_LABELS[readinessState]}</LemonTag>
}
