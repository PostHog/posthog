import { Link } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { isURL } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { formatBreakdownType } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { BreakdownFilter } from '~/queries/schema/schema-general'

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
    formatItemBreakdownLabel: (item: IndexedTrendResult) => string
}

export function BreakdownColumnItem({ item, formatItemBreakdownLabel }: BreakdownColumnItemProps): JSX.Element {
    const breakdownLabel = formatItemBreakdownLabel(item)
    const formattedLabel = stringWithWBR(breakdownLabel, 20)

    return (
        <div className="flex justify-between items-center">
            {breakdownLabel && (
                <>
                    {isURL(breakdownLabel) ? (
                        <Link to={breakdownLabel} target="_blank" className="value-link font-medium" targetBlankIcon>
                            {formattedLabel}
                        </Link>
                    ) : (
                        <div title={breakdownLabel} className="font-medium">
                            {formattedLabel}
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
