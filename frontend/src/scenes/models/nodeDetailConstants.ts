import { LemonTagType } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

export const NODE_TYPE_TAG_SETTINGS: Record<
    DataModelingNodeType,
    { label: string; type: LemonTagType; color: string }
> = {
    table: { label: 'Table', type: 'default', color: 'var(--muted)' },
    view: { label: 'View', type: 'primary', color: 'var(--primary-3000)' },
    matview: { label: 'Materialized view', type: 'success', color: 'var(--success)' },
    endpoint: { label: 'Endpoint', type: 'completion', color: 'var(--purple)' },
}

export const STATUS_TAG_SETTINGS: Record<string, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    Cancelled: 'muted',
    Modified: 'warning',
}
