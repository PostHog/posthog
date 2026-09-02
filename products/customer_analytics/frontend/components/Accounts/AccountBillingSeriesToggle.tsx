import { LemonButton, LemonSnack } from '@posthog/lemon-ui'
import type { LegendItem } from '@posthog/quill-charts'

import { LemonColorGlyph } from 'lib/lemon-ui/LemonColor/LemonColorGlyph'
import { cn } from 'lib/utils/css-classes'

import { AccountBillingKind } from './accountBillingLogic'

export function AccountBillingSeriesToggle({
    series,
    hiddenKeys,
    kind,
    onToggle,
    onToggleAll,
}: {
    series: LegendItem[]
    hiddenKeys: string[]
    kind: AccountBillingKind
    onToggle: (seriesKey: string) => void
    onToggleAll: (hidden: boolean) => void
}): JSX.Element {
    const hidden = new Set(hiddenKeys)
    // Counted against the current series, not hiddenKeys.length, because the state can hold keys the data no longer has.
    const hiddenCount = series.filter(({ key }) => hidden.has(key)).length

    return (
        <div className="flex flex-wrap items-center gap-1" data-attr={`account-billing-series-toggle-${kind}`}>
            {series.map(({ key, label, color }) => {
                const isHidden = hidden.has(key)
                return (
                    <LemonSnack
                        key={key}
                        onClick={() => onToggle(key)}
                        title={isHidden ? `Show ${label}` : `Hide ${label}`}
                        className={cn('cursor-pointer', isHidden && 'opacity-50')}
                    >
                        <span className="flex items-center gap-1">
                            <LemonColorGlyph color={color} size="small" />
                            <span className={cn(isHidden && 'line-through')}>{label}</span>
                        </span>
                    </LemonSnack>
                )
            })}
            <LemonButton
                size="xsmall"
                type="tertiary"
                onClick={() => onToggleAll(false)}
                disabledReason={hiddenCount === 0 ? 'All series are already shown' : undefined}
                data-attr="account-billing-series-select-all"
            >
                Select all
            </LemonButton>
            <LemonButton
                size="xsmall"
                type="tertiary"
                onClick={() => onToggleAll(true)}
                disabledReason={hiddenCount === series.length ? 'All series are already hidden' : undefined}
                data-attr="account-billing-series-clear-all"
            >
                Clear all
            </LemonButton>
        </div>
    )
}
