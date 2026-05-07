import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { BulkSelectionConfig, BulkSelectionContext } from './useBulkSelection'

export interface BulkSelectionBarProps<T extends Record<string, any>> {
    context: BulkSelectionContext<T>
    config: BulkSelectionConfig<T>
    noun: [string, string]
}

export function BulkSelectionBar<T extends Record<string, any>>({
    context,
    config,
    noun,
}: BulkSelectionBarProps<T>): JSX.Element | null {
    if (context.selectedCount === 0) {
        return null
    }
    const [singular, plural] = noun
    const word = context.selectedCount === 1 ? singular : plural

    return (
        <div className="flex items-center justify-end gap-2 min-h-9 LemonTable__bulk-selection-bar">
            <span className="text-secondary text-sm">
                {context.selectedCount} {word} selected
            </span>
            <LemonButton type="secondary" size="small" onClick={context.clearSelection}>
                Clear
            </LemonButton>
            {config.renderActions(context)}
        </div>
    )
}
