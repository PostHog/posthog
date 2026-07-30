import { LemonSnack } from '@posthog/lemon-ui'
import type { LegendItem } from '@posthog/quill-charts'

import { LemonColorGlyph } from 'lib/lemon-ui/LemonColor/LemonColorGlyph'
import { cn } from 'lib/utils/css-classes'

import { AccountBillingKind } from './accountBillingLogic'

export function AccountBillingSeriesToggle({
    series,
    hiddenKeys,
    kind,
    onToggle,
}: {
    series: LegendItem[]
    hiddenKeys: string[]
    kind: AccountBillingKind
    onToggle: (seriesKey: string) => void
}): JSX.Element {
    const hidden = new Set(hiddenKeys)

    return (
        <div className="flex flex-wrap gap-1" data-attr={`account-billing-series-toggle-${kind}`}>
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
        </div>
    )
}
