import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { formatBreakdownType } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { BreakdownFilter } from '~/queries/schema'

type BreakdownColumnTitleProps = { breakdownFilter: BreakdownFilter }

export function BreakdownColumnTitle({ breakdownFilter }: BreakdownColumnTitleProps): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value={formatBreakdownType(breakdownFilter)} />
}

type BreakdownColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    isMainInsightView: boolean
    toggleVisibility: (id: number) => void
    formatItemBreakdownLabel: (item: IndexedTrendResult) => string
}

export function BreakdownColumnItem({
    item,
    canCheckUncheckSeries,
    isMainInsightView,
    toggleVisibility,
    formatItemBreakdownLabel,
}: BreakdownColumnItemProps): JSX.Element {
    const breakdownLabel = formatItemBreakdownLabel(item)
    const multiEntityAndToggleable = !isMainInsightView && canCheckUncheckSeries
    return (
        <div
            className={multiEntityAndToggleable ? 'cursor-pointer' : ''}
            onClick={multiEntityAndToggleable ? () => toggleVisibility(item.id) : undefined}
        >
            {breakdownLabel && <div title={breakdownLabel}>{stringWithWBR(breakdownLabel, 20)}</div>}
        </div>
    )
}
