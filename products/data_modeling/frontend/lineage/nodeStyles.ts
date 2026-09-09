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
    Skipped: 'muted',
    Modified: 'warning',
}

/**
 * Statuses a reader cannot act on from the word alone. `Skipped` is the one that gets asked about:
 * nothing about the model itself went wrong, so the tag has to say where to look instead.
 */
export const STATUS_TOOLTIPS: Record<string, string> = {
    Skipped: 'Skipped in the last scheduled run because a model it depends on failed.',
    Cancelled: 'The run was stopped before it finished.',
    Modified: 'The query changed after the last run, so the stored data is behind it.',
}

/**
 * Tag colors cannot fill a solid mark: LemonTag tints its background, so its `primary` becomes raw
 * brand orange when filled, one hue off danger red. A mark with no text needs its own palette.
 */
export const STATUS_MARK_BACKGROUNDS: Record<string, string> = {
    Running: 'bg-warning',
    Completed: 'bg-success',
    Failed: 'bg-danger',
    Cancelled: 'bg-muted',
    Skipped: 'bg-muted',
    Modified: 'bg-warning',
}

/** Background for a status mark that carries no text of its own, such as a run-history square. */
export function statusBackgroundClass(status: string): string {
    return STATUS_MARK_BACKGROUNDS[status] ?? 'bg-muted'
}
