import type { LemonTagType } from '@posthog/lemon-ui'

import { StatusTagSetting } from 'products/data_warehouse/frontend/utils'

export type QuillBadgeVariant = 'default' | 'info' | 'destructive' | 'warning' | 'success' | 'completed'

export const RUN_STATUS_BADGE_VARIANTS: Record<string, QuillBadgeVariant> = {
    Completed: 'success',
    Failed: 'destructive',
    Running: 'warning',
    Cancelled: 'default',
    Skipped: 'default',
    Modified: 'warning',
}

export function runStatusLabel(status: string): string {
    return status === 'Cancelled' ? 'Canceled' : status
}

const LEMON_TAG_BADGE_VARIANTS: Partial<Record<LemonTagType, QuillBadgeVariant>> = {
    primary: 'info',
    success: 'success',
    danger: 'destructive',
    warning: 'warning',
}

export function schemaStatusBadgeVariant(status: keyof typeof StatusTagSetting): QuillBadgeVariant {
    return LEMON_TAG_BADGE_VARIANTS[StatusTagSetting[status]] ?? 'default'
}

export const DATA_WAREHOUSE_ICON_COLOR = 'var(--color-product-data-warehouse-light)'
