import { LemonTagType } from '@posthog/lemon-ui'

import { DataModelingNodeType } from '~/types'

export const NODE_TYPE_SETTINGS: Record<DataModelingNodeType, { label: string; color: string }> = {
    table: { label: 'Table', color: 'var(--muted)' },
    view: { label: 'View', color: 'var(--primary-3000)' },
    matview: { label: 'Materialized view', color: 'var(--success)' },
    endpoint: { label: 'Endpoint', color: 'var(--purple)' },
}

export const STATUS_TAG_SETTINGS: Record<string, LemonTagType> = {
    Running: 'primary',
    Completed: 'success',
    Failed: 'danger',
    Cancelled: 'muted',
    Modified: 'warning',
}
