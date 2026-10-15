import { LemonDialog } from 'lib/lemon-ui/LemonDialog'

import type { ExistingMetric } from './common'

export function openOverwriteMetricDialog({
    existing,
    onOverwrite,
    onCancel,
}: {
    existing: ExistingMetric
    onOverwrite: () => void
    onCancel?: () => void
}): void {
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
            onClick: onOverwrite,
            'data-attr': 'data-catalog-overwrite-metric-confirm',
        },
        secondaryButton: { children: 'Cancel', onClick: onCancel },
    })
}
