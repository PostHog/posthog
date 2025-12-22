import { IconPin, IconPinFilled } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { isURL } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { formatBreakdownType } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { BreakdownFilter } from '~/queries/schema/schema-general'

interface BreakdownColumnTitleProps {
    breakdownFilter: BreakdownFilter
    isPinned?: boolean
    onTogglePin?: () => void
}

export function BreakdownColumnTitle({
    breakdownFilter,
    isPinned,
    onTogglePin,
}: BreakdownColumnTitleProps): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <PropertyKeyInfo disableIcon disablePopover value={formatBreakdownType(breakdownFilter)} />
            {onTogglePin && (
                <Tooltip title={isPinned ? 'Unpin column' : 'Pin column'}>
                    <span
                        className="inline-flex items-center justify-center cursor-pointer p-1 -m-1"
                        onClick={(e) => {
                            e.stopPropagation()
                            onTogglePin()
                        }}
                    >
                        {isPinned ? <IconPinFilled className="text-sm" /> : <IconPin className="text-sm" />}
                    </span>
                </Tooltip>
            )}
        </div>
    )
}

interface MultipleBreakdownColumnTitleProps {
    children?: string | null
    isPinned?: boolean
    onTogglePin?: () => void
}

export function MultipleBreakdownColumnTitle({
    children,
    isPinned,
    onTogglePin,
}: MultipleBreakdownColumnTitleProps): JSX.Element {
    return (
        <div className="flex items-center gap-1">
            <PropertyKeyInfo disableIcon disablePopover value={children || 'Breakdown Value'} />
            {onTogglePin && (
                <Tooltip title={isPinned ? 'Unpin column' : 'Pin column'}>
                    <span
                        className="inline-flex items-center justify-center cursor-pointer p-1 -m-1"
                        onClick={(e) => {
                            e.stopPropagation()
                            onTogglePin()
                        }}
                    >
                        {isPinned ? <IconPinFilled className="text-sm" /> : <IconPin className="text-sm" />}
                    </span>
                </Tooltip>
            )}
        </div>
    )
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
