import './InsightLabel.scss'

import clsx from 'clsx'
import { useValues } from 'kea'

import { LemonTag } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { hexToRGBA } from 'lib/utils/colors'
import { capitalizeFirstLetter, midEllipsis } from 'lib/utils/strings'
import { formatEventName } from 'scenes/insights/utils'
import { ResultSeries, getResultSeriesCustomName } from 'scenes/insights/utils/resultSeries'

import { groupsModel } from '~/models/groupsModel'
import { BreakdownKeyType } from '~/types'

import { mathsLogic } from 'products/product_analytics/frontend/insights/trends/mathsLogic'

import { TaxonomicFilterGroupType } from '../TaxonomicFilter/types'

export enum IconSize {
    Small = 'small',
    Medium = 'medium',
    Large = 'large',
}

// InsightsLabel pretty prints the series a result row reports
interface InsightsLabelProps {
    seriesColor?: string
    /** The result row's series, from `getResultSeries`. */
    series?: ResultSeries | null
    value?: string
    className?: string
    breakdownValue?: BreakdownKeyType
    compareValue?: string
    hideBreakdown?: boolean // Whether to hide the breakdown detail in the label
    hideCompare?: boolean // Whether to hide the compare detail in the label
    hideIcon?: boolean // Whether to hide the icon that showcases the color of the series
    iconSize?: IconSize // Size of the series color icon
    iconStyle?: Record<string, any> // style on series color icon
    seriesStatus?: string // Used by lifecycle chart to display the series name
    fallbackName?: string // Name to display when the label has no series to name, e.g. on a formula row
    hasMultipleSeries?: boolean // Whether the query defines multiple series (not breakdown values). Derived from !isSingleSeriesDefinition.
    showCountedByTag?: boolean // Force 'counted by' tag to show (always shown when the series math is set)
    allowWrap?: boolean // Allow wrapping to multiple lines (useful for long values like URLs)
    onLabelClick?: () => void // Click handler for inner label
    showEventName?: boolean // Override internally calculated to always show event name
    showSingleName?: boolean // If label has default name and custom name, only show custom name. By default show both.
    pillMidEllipsis?: boolean // Whether to use mid ellipsis if pill text needs to be truncated
    pillMaxWidth?: number // Max width of each pill in px
    showPathCleaningHighlight?: boolean // Whether to show path cleaning highlights on the breakdown value
    /** When true, hides the HogQL/SQL math tag when the series has a custom name set.
     *  Pass only in legend rows — not in tooltips — to prevent long SQL expressions eating label space. */
    hideHogQLTagWhenCustomName?: boolean
}

interface MathTagProps {
    math: string | undefined
    mathProperty: string | undefined | null
    mathHogQL: string | undefined | null
    mathGroupTypeIndex: number | null | undefined
}

function MathTag({ math, mathProperty, mathHogQL, mathGroupTypeIndex }: MathTagProps): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)
    const { aggregationLabel } = useValues(groupsModel)

    if (!math || math === 'total') {
        return <LemonTag>Total</LemonTag>
    }
    if (math === 'dau') {
        return <LemonTag>Unique</LemonTag>
    }
    if (math === 'unique_group' && mathGroupTypeIndex != undefined) {
        return <LemonTag>Unique {aggregationLabel(mathGroupTypeIndex).plural}</LemonTag>
    }
    if (math === 'weekly_active' && mathGroupTypeIndex != undefined) {
        return <LemonTag>Weekly active {aggregationLabel(mathGroupTypeIndex).plural}</LemonTag>
    }
    if (math === 'monthly_active' && mathGroupTypeIndex != undefined) {
        return <LemonTag>Monthly active {aggregationLabel(mathGroupTypeIndex).plural}</LemonTag>
    }
    if (math && ['sum', 'avg', 'min', 'max', 'median', 'p75', 'p90', 'p95', 'p99'].includes(math)) {
        return (
            <>
                <LemonTag>{mathDefinitions[math]?.name || capitalizeFirstLetter(math)}</LemonTag>
                {mathProperty && (
                    <>
                        <span className="shrink-0">of</span>
                        <PropertyKeyInfo disableIcon value={mathProperty} />
                    </>
                )}
            </>
        )
    }
    if (math === 'hogql') {
        return <LemonTag className="max-w-60 text-ellipsis overflow-hidden">{String(mathHogQL) || 'SQL'}</LemonTag>
    }
    // Use mathDefinitions first, then fall back to capitalizing the math string
    return <LemonTag>{mathDefinitions[math]?.name || capitalizeFirstLetter(math)}</LemonTag>
}

export function InsightLabel({
    seriesColor = '#000000',
    series,
    value,
    className,
    breakdownValue,
    compareValue,
    hideBreakdown,
    hideCompare,
    hideIcon,
    iconSize = IconSize.Large,
    iconStyle,
    seriesStatus,
    fallbackName,
    hasMultipleSeries,
    showCountedByTag,
    allowWrap = false,
    showEventName: _showEventName = false,
    onLabelClick,
    pillMidEllipsis = false,
    pillMaxWidth,
    showSingleName = false,
    showPathCleaningHighlight = false,
    hideHogQLTagWhenCustomName = false,
}: InsightsLabelProps): JSX.Element {
    const showEventName = _showEventName || !breakdownValue || (hasMultipleSeries && !Array.isArray(breakdownValue))

    const entity = series?.node
    const math = series?.math
    const seriesIndex = series?.node ? series.order : undefined
    const customName = entity ? getResultSeriesCustomName(entity) : null
    const displayEntity = entity ? { ...entity, name: formatEventName(entity.name) } : undefined

    const eventName = seriesStatus
        ? capitalizeFirstLetter(seriesStatus)
        : displayEntity?.name || formatEventName(fallbackName) || ''

    const iconSizePx = iconSize === IconSize.Large ? 14 : iconSize === IconSize.Medium ? 12 : 10
    const pillValues = [...(hideBreakdown ? [] : [breakdownValue].flat()), hideCompare ? null : compareValue].filter(
        (pill) => !!pill
    )

    return (
        <div className={clsx('insights-label', className)} data-attr="insight-label">
            <div className="flex items-center w-fit">
                {!(hasMultipleSeries && !breakdownValue) && !hideIcon && (
                    <div
                        className="color-icon"
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{
                            background: seriesColor,
                            boxShadow: `0px 0px 0px 1px ${hexToRGBA(seriesColor, 0.5)}`,
                            minWidth: iconSizePx,
                            minHeight: iconSizePx,
                            width: iconSizePx,
                            height: iconSizePx,
                            ...iconStyle,
                        }}
                    />
                )}
                {hasMultipleSeries && !hideIcon && seriesIndex !== undefined && (
                    <SeriesLetter seriesIndex={seriesIndex} seriesColor={seriesColor} hasBreakdown={!!breakdownValue} />
                )}
                <div
                    className={clsx('flex items-center w-fit gap-x-2', allowWrap && 'flex-wrap')}
                    onClick={onLabelClick}
                >
                    {showEventName && (
                        <>
                            {displayEntity ? (
                                <EntityFilterInfo
                                    filter={displayEntity}
                                    allowWrap={allowWrap}
                                    showSingleName={showSingleName}
                                />
                            ) : (
                                <PropertyKeyInfo
                                    disableIcon
                                    disablePopover
                                    value={eventName}
                                    ellipsis={!allowWrap}
                                    type={TaxonomicFilterGroupType.Events}
                                />
                            )}
                        </>
                    )}

                    {((math?.math && math.math !== 'total') || showCountedByTag) &&
                        !(hideHogQLTagWhenCustomName && customName && math?.math === 'hogql') && (
                            <div className="insights-label__math flex flex-nowrap items-center gap-x-1">
                                <MathTag
                                    math={math?.math}
                                    mathProperty={math?.math_property}
                                    mathHogQL={math?.math_hogql}
                                    mathGroupTypeIndex={math?.math_group_type_index}
                                />
                            </div>
                        )}

                    {pillValues.length > 0 && (
                        <div className="flex flex-wrap gap-1">
                            {pillValues.map((pill) => (
                                <Tooltip title={pill} key={pill}>
                                    <LemonTag className="tag-pill">
                                        {/* eslint-disable-next-line react/forbid-dom-props */}
                                        <span className="truncate" style={{ maxWidth: pillMaxWidth }}>
                                            {showPathCleaningHighlight
                                                ? parseAliasToReadable(pill?.toString() ?? '')
                                                : pillMidEllipsis
                                                  ? midEllipsis(String(pill), 50)
                                                  : pill}
                                        </span>
                                    </LemonTag>
                                </Tooltip>
                            ))}
                        </div>
                    )}
                </div>
            </div>
            {value && <span className="value">{value}</span>}
        </div>
    )
}
