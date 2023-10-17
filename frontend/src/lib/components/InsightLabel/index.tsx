import { Space, Tag } from 'antd'
import { ActionFilter, BreakdownKeyType } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, hexToRGBA, midEllipsis } from 'lib/utils'
import './InsightLabel.scss'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { useValues } from 'kea'
import { mathsLogic } from 'scenes/trends/mathsLogic'
import clsx from 'clsx'
import { groupsModel } from '~/models/groupsModel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export enum IconSize {
    Small = 'small',
    Medium = 'medium',
    Large = 'large',
}

// InsightsLabel pretty prints the action (or event) returned from /insights
interface InsightsLabelProps {
    seriesColor?: string
    action?: ActionFilter
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
    fallbackName?: string // Name to display for the series if it can be determined from `action`
    hasMultipleSeries?: boolean // Whether the graph has multiple discrete series (not breakdown values)
    showCountedByTag?: boolean // Force 'counted by' tag to show (always shown when action.math is set)
    allowWrap?: boolean // Allow wrapping to multiple lines (useful for long values like URLs)
    onLabelClick?: () => void // Click handler for inner label
    showEventName?: boolean // Override internally calculated to always show event name
    showSingleName?: boolean // If label has default name and custom name, only show custom name. By default show both.
    pillMidEllipsis?: boolean // Whether to use mid ellipsis if pill text needs to be truncated
    pillMaxWidth?: number // Max width of each pill in px
}

interface MathTagProps {
    math: string | undefined
    mathProperty: string | undefined
    mathHogQL: string | undefined
    mathGroupTypeIndex: number | null | undefined
}

function MathTag({ math, mathProperty, mathHogQL, mathGroupTypeIndex }: MathTagProps): JSX.Element {
    const { mathDefinitions } = useValues(mathsLogic)
    const { aggregationLabel } = useValues(groupsModel)

    if (!math || math === 'total') {
        return <Tag>Total</Tag>
    }
    if (math === 'dau') {
        return <Tag>Unique</Tag>
    }
    if (math === 'unique_group' && mathGroupTypeIndex != undefined) {
        return <Tag>Unique {aggregationLabel(mathGroupTypeIndex).plural}</Tag>
    }
    if (math && ['sum', 'avg', 'min', 'max', 'median', 'p90', 'p95', 'p99'].includes(math || '')) {
        return (
            <>
                <Tag>{mathDefinitions[math]?.name || capitalizeFirstLetter(math)}</Tag>
                {mathProperty && (
                    <>
                        <span>of</span>
                        <PropertyKeyInfo disableIcon value={mathProperty} />
                    </>
                )}
            </>
        )
    }
    if (math === 'hogql') {
        return (
            <Tag title={String(mathHogQL)} className="max-w-60 text-ellipsis overflow-hidden">
                {String(mathHogQL)}
            </Tag>
        )
    }
    return <Tag>{capitalizeFirstLetter(math)}</Tag>
}

export function InsightLabel({
    seriesColor = '#000000',
    action,
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
}: InsightsLabelProps): JSX.Element {
    const showEventName = _showEventName || !breakdownValue || (hasMultipleSeries && !Array.isArray(breakdownValue))
    const eventName = seriesStatus ? capitalizeFirstLetter(seriesStatus) : action?.name || fallbackName || ''
    const iconSizePx = iconSize === IconSize.Large ? 14 : iconSize === IconSize.Medium ? 12 : 10
    const pillValues = [...(hideBreakdown ? [] : [breakdownValue].flat()), hideCompare ? null : compareValue].filter(
        (pill) => !!pill
    )

    return (
        <div className={clsx('insights-label', className)}>
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
                {hasMultipleSeries && !hideIcon && action?.order !== undefined && (
                    <SeriesLetter
                        seriesIndex={action.order}
                        seriesColor={seriesColor}
                        hasBreakdown={!!breakdownValue}
                    />
                )}
                <div
                    className={clsx('flex items-center w-fit gap-x-2', allowWrap && 'flex-wrap')}
                    onClick={onLabelClick}
                >
                    {showEventName && (
                        <>
                            {action ? (
                                <EntityFilterInfo
                                    filter={action}
                                    allowWrap={allowWrap}
                                    showSingleName={showSingleName}
                                />
                            ) : (
                                <PropertyKeyInfo disableIcon disablePopover value={eventName} ellipsis={!allowWrap} />
                            )}
                        </>
                    )}

                    {((action?.math && action.math !== 'total') || showCountedByTag) && (
                        <MathTag
                            math={action?.math}
                            mathProperty={action?.math_property}
                            mathHogQL={action?.math_hogql}
                            mathGroupTypeIndex={action?.math_group_type_index}
                        />
                    )}

                    {pillValues.length > 0 && (
                        <Space direction={'horizontal'} wrap={true}>
                            {pillValues.map((pill) => (
                                <Tooltip title={pill} key={pill}>
                                    <Tag className="tag-pill" closable={false}>
                                        {/* eslint-disable-next-line react/forbid-dom-props */}
                                        <span className="truncate" style={{ maxWidth: pillMaxWidth }}>
                                            {pillMidEllipsis ? midEllipsis(String(pill), 50) : pill}
                                        </span>
                                    </Tag>
                                </Tooltip>
                            ))}
                        </Space>
                    )}
                </div>
            </div>
            {value && <span className="value">{value}</span>}
        </div>
    )
}
