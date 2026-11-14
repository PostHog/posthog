import type { InsightCardMenuPlacement } from 'lib/components/Cards/InsightCard/insightCardMenu'
import type { Dayjs } from 'lib/dayjs'

export interface WidgetCardMenuDescription {
    label: string
    onClick: () => void
}

export interface WidgetCardMenuRefresh {
    onRefresh: () => void
    disabledReason?: string
    lastRefresh?: string | number | Dayjs | null
}

export interface WidgetCardMenu {
    viewUrl: string | null
    edit: (() => void) | null
    duplicate: (() => void) | null
    dashboard: {
        description: WidgetCardMenuDescription | null
        placement: InsightCardMenuPlacement | null
        remove: (() => void) | null
    } | null
    refresh: WidgetCardMenuRefresh | null
}

export function buildWidgetCardMenu({
    viewUrl,
    onEdit,
    onDuplicate,
    description,
    placement,
    onRemove,
    refresh,
}: {
    viewUrl?: string
    onEdit?: () => void
    onDuplicate?: () => void
    description?: WidgetCardMenuDescription
    placement?: InsightCardMenuPlacement
    onRemove?: () => void
    refresh?: WidgetCardMenuRefresh
}): WidgetCardMenu {
    return {
        viewUrl: viewUrl ?? null,
        edit: onEdit ?? null,
        duplicate: onDuplicate ?? null,
        dashboard:
            description || placement || onRemove
                ? { description: description ?? null, placement: placement ?? null, remove: onRemove ?? null }
                : null,
        refresh: refresh ?? null,
    }
}
