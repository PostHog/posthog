import { router } from 'kea-router'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { DataCatalogMetricNameConflictExistingApi } from './generated/api.schemas'

export function openOverwriteMetricDialog({
    existing,
    onOverwrite,
    onCancel,
}: {
    existing: DataCatalogMetricNameConflictExistingApi
    onOverwrite: () => void
    onCancel?: () => void
}): void {
    // Escape, the close icon, and an outside click skip the buttons, so every close that is not an overwrite counts as a cancel.
    // A close caused by navigation is the exception, because the cancel path would reopen the save form on the next page.
    let overwriting = false
    const openedAt = router.values.location.pathname
    LemonDialog.open({
        title: 'Overwrite the existing metric?',
        content: (
            <div className="flex flex-col gap-2 text-sm text-secondary">
                <span>
                    A metric named <code>{existing.name}</code> already exists. Overwriting it replaces its fields with
                    the values you entered.
                </span>
                {existing.status === 'approved' && (
                    <span>
                        This metric is approved. If you change its description, unit, or definition, it goes back to
                        proposed and needs approval again.
                    </span>
                )}
            </div>
        ),
        primaryButton: {
            children: 'Overwrite',
            status: 'danger',
            onClick: () => {
                overwriting = true
                onOverwrite()
            },
            'data-attr': 'data-catalog-overwrite-metric-confirm',
        },
        secondaryButton: { children: 'Cancel' },
        onAfterClose: () => {
            if (!overwriting && router.values.location.pathname === openedAt) {
                onCancel?.()
            }
        },
    })
}
