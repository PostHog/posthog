import { ApiError } from 'lib/api'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import type { LemonDialogProps } from 'lib/lemon-ui/LemonDialog'

export interface BreakingColumnChange {
    removedColumns: string[]
    affectedViews: string[]
    affectedViewCount: number
    hasHiddenAffectedViews: boolean
}

/** Thrown when the user cancels a breaking column change, so a save flow can stop without a failure toast. */
export class BreakingColumnChangeDeclinedError extends Error {
    constructor() {
        super('Breaking column change declined')
        this.name = 'BreakingColumnChangeDeclinedError'
    }
}

export function getBreakingColumnChange(error: unknown): BreakingColumnChange | null {
    if (!(error instanceof ApiError) || error.code !== 'breaking_column_change') {
        return null
    }
    const extra = error.data?.extra
    if (!extra || !Array.isArray(extra.removed_columns) || !Array.isArray(extra.affected_views)) {
        return null
    }
    return {
        removedColumns: extra.removed_columns.filter((column: unknown): column is string => typeof column === 'string'),
        affectedViews: extra.affected_views.filter((view: unknown): view is string => typeof view === 'string'),
        affectedViewCount: typeof extra.affected_view_count === 'number' ? extra.affected_view_count : 0,
        hasHiddenAffectedViews: extra.has_hidden_affected_views === true,
    }
}

export function confirmBreakingColumnChange(change: BreakingColumnChange): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
        LemonDialog.open(
            getBreakingColumnChangeDialogProps(
                change,
                () => resolve(true),
                () => resolve(false)
            )
        )
    })
}

export function getBreakingColumnChangeDialogProps(
    change: BreakingColumnChange,
    onConfirm: () => void,
    onCancel: () => void
): LemonDialogProps {
    const remainingVisibleViews = Math.max(change.affectedViewCount - change.affectedViews.length, 0)
    return {
        title: 'Save breaking changes?',
        description: (
            <div className="space-y-2">
                <p>
                    This change removes{' '}
                    {change.removedColumns.map((column, index) => (
                        <span key={column}>
                            {index > 0 ? ', ' : ''}
                            <code>{column}</code>
                        </span>
                    ))}
                    .
                </p>
                {change.affectedViews.length > 0 && (
                    <p>
                        It will break {change.affectedViews.join(', ')}
                        {remainingVisibleViews > 0 ? ` and ${remainingVisibleViews} more` : ''}.
                    </p>
                )}
                {change.hasHiddenAffectedViews && <p>It will also break one or more views that you cannot access.</p>}
                <p>Update the downstream views after you save this view.</p>
            </div>
        ),
        primaryButton: {
            children: 'Save anyway',
            status: 'danger',
            onClick: onConfirm,
        },
        secondaryButton: {
            children: 'Cancel',
        },
        onAfterClose: onCancel,
    }
}
