import type { LemonDialogProps } from 'lib/lemon-ui/LemonDialog'

export interface BreakingColumnChange {
    removedColumns: string[]
    affectedViews: string[]
    affectedViewCount: number
    hasHiddenAffectedViews: boolean
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
