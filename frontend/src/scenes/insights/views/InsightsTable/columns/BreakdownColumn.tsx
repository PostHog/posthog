import { Link } from '@posthog/lemon-ui'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { isURL } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { formatBreakdownType } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { BreakdownFilter } from '~/queries/schema'

interface BreakdownColumnTitleProps {
    breakdownFilter: BreakdownFilter
}

export function BreakdownColumnTitle({ breakdownFilter }: BreakdownColumnTitleProps): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value={formatBreakdownType(breakdownFilter)} />
}

interface MultipleBreakdownColumnTitleProps {
    children?: string | null
}

export function MultipleBreakdownColumnTitle({ children }: MultipleBreakdownColumnTitleProps): JSX.Element {
    return <PropertyKeyInfo disableIcon disablePopover value={children || 'Breakdown Value'} />
}

type BreakdownColumnItemProps = {
    item: IndexedTrendResult
    canCheckUncheckSeries: boolean
    isMainInsightView: boolean
    toggleHiddenLegendIndex: (index: number) => void
    formatItemBreakdownLabel: (item: IndexedTrendResult) => string
}

export function BreakdownColumnItem({
    item,
    canCheckUncheckSeries,
    isMainInsightView,
    toggleHiddenLegendIndex,
    formatItemBreakdownLabel,
}: BreakdownColumnItemProps): JSX.Element {
    const breakdownLabel = formatItemBreakdownLabel(item)
    const formattedLabel = stringWithWBR(breakdownLabel, 20)
    const multiEntityAndToggleable = !isMainInsightView && canCheckUncheckSeries
    return (
        <div
            className={multiEntityAndToggleable ? 'cursor-pointer' : ''}
            onClick={multiEntityAndToggleable ? () => toggleHiddenLegendIndex(item.id) : undefined}
        >
            {breakdownLabel && (
                <>
                    {isURL(breakdownLabel) ? (
                        <Link to={breakdownLabel} target="_blank" className="value-link" targetBlankIcon>
                            {formattedLabel}
                        </Link>
                    ) : (
                        <div title={breakdownLabel}>{formattedLabel}</div>
                    )}
                </>
            )}
        </div>
    )
}
