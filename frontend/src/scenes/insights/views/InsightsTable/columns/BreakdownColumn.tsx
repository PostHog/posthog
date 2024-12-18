import { Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { isURL } from 'lib/utils'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { useState } from 'react'
import { insightLogic } from 'scenes/insights/insightLogic'
import { formatBreakdownType } from 'scenes/insights/utils'
import { IndexedTrendResult } from 'scenes/trends/types'

import { BreakdownFilter } from '~/queries/schema'

import { resultCustomizationsModalLogic } from '../../../../../queries/nodes/InsightViz/resultCustomizationsModalLogic'
import { CustomizationIcon } from './SeriesColumn'

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
    const [isHovering, setIsHovering] = useState(false)
    const { insightProps } = useValues(insightLogic)
    const { hasInsightColors } = useValues(resultCustomizationsModalLogic(insightProps))
    const { openModal } = useActions(resultCustomizationsModalLogic(insightProps))

    const breakdownLabel = formatItemBreakdownLabel(item)
    const formattedLabel = stringWithWBR(breakdownLabel, 20)

    return (
        <div
            className={clsx('flex justify-between items-center', { 'cursor-pointer': hasInsightColors })}
            onClick={hasInsightColors ? () => openModal(item) : undefined}
            onMouseEnter={() => setIsHovering(true)}
            onMouseLeave={() => setIsHovering(false)}
        >
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

                    <CustomizationIcon isVisible={isHovering} />
                </>
            )}
        </div>
    )
}
