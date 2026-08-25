import clsx from 'clsx'
import { createPortal } from 'react-dom'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { BulkSelectionConfig, BulkSelectionContext, BulkSelectionKey } from './useBulkSelection'

export interface BulkSelectionBarProps<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey> {
    context: BulkSelectionContext<T, K>
    config: BulkSelectionConfig<T, K>
    noun: [string, string]
}

export function BulkSelectionBar<T extends Record<string, any>, K extends BulkSelectionKey = BulkSelectionKey>({
    context,
    config,
    noun,
}: BulkSelectionBarProps<T, K>): JSX.Element | null {
    if (context.selectedCount === 0) {
        return null
    }
    const [singular, plural] = noun
    const word = context.selectedCount === 1 ? singular : plural

    const bar = (
        <div
            className={clsx(
                'flex items-center justify-end gap-2 min-h-9 px-1 LemonTable__bulk-selection-bar',
                config.barClassName
            )}
        >
            <span className="text-secondary text-sm">
                {context.selectedCount} {word} selected
            </span>
            <LemonButton type="secondary" size="small" onClick={context.clearSelection}>
                Clear
            </LemonButton>
            {config.renderActions(context)}
        </div>
    )

    return config.barPortalTarget ? createPortal(bar, config.barPortalTarget) : bar
}
