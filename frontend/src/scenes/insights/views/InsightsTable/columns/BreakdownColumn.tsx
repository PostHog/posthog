import { IconGear } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'

import { isURL } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'

import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownType } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { BreakdownFilter } from '~/queries/schema'

import { legendEntryModalLogic } from '../legendEntryModalLogic'

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
    const { insightProps } = useValues(insightLogic)
    const { openModal } = useActions(legendEntryModalLogic(insightProps))

    const breakdownLabel = formatItemBreakdownLabel(item)
    const formattedLabel = stringWithWBR(breakdownLabel, 20)

    return (
        <div className="flex">
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

                    <Link
                        className="align-middle"
                        onClick={(e) => {
                            e.preventDefault()
                            e.stopPropagation()

                            openModal(item)
                        }}
                    >
                        <IconGear fontSize={16} />
                    </Link>
                </>
            )}
        </div>
    )
}
