import React from 'react'
import { Col, Row, Tag } from 'antd'
import { ActionFilter } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, hexToRGBA } from 'lib/utils'
import './InsightLabel.scss'
import { MATHS } from 'lib/constants'
import { SeriesLetter } from 'lib/components/SeriesGlyph'
import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'

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
    breakdownValue?: string | number
    hideBreakdown?: boolean // Whether to hide the breakdown detail in the label
    hideIcon?: boolean // Whether to hide the icon that showcases the color of the series
    iconSize?: IconSize // Size of the series color icon
    iconStyle?: Record<string, any> // style on series color icon
    seriesStatus?: string // Used by lifecycle chart to display the series name
    fallbackName?: string // Name to display for the series if it can be determined from `action`
    hasMultipleSeries?: boolean // Whether the graph has multiple discrete series (not breakdown values)
    showCountedByTag?: boolean // Force 'counted by' tag to show (always shown when action.math is set)
    allowWrap?: boolean // Allow wrapping to multiple lines (useful for long values like URLs)
    useCustomName?: boolean // Whether to show new custom name (FF `6063-rename-filters`). `{custom_name} ({id})`.
}

function MathTag({ math, mathProperty }: Record<string, string | undefined>): JSX.Element {
    if (!math || math === 'total') {
        return <Tag>Total</Tag>
    }
    if (math === 'dau') {
        return <Tag>Unique</Tag>
    }
    if (math && ['sum', 'avg', 'min', 'max', 'median', 'p90', 'p95', 'p99'].includes(math || '')) {
        return (
            <>
                <Tag>{MATHS[math]?.name || capitalizeFirstLetter(math)}</Tag>
                {mathProperty && (
                    <>
                        <span style={{ paddingLeft: 4, paddingRight: 2 }}>of</span>
                        <PropertyKeyInfo disableIcon value={mathProperty} />
                    </>
                )}
            </>
        )
    }
    return <Tag>{capitalizeFirstLetter(math)}</Tag>
}

export function InsightLabel({
    seriesColor = '#000000',
    action,
    value,
    breakdownValue,
    hideBreakdown,
    hideIcon,
    iconSize = IconSize.Large,
    iconStyle,
    seriesStatus,
    fallbackName,
    hasMultipleSeries,
    showCountedByTag,
    allowWrap = false,
    useCustomName = false,
}: InsightsLabelProps): JSX.Element {
    const showEventName = !breakdownValue || hasMultipleSeries
    const eventName = seriesStatus ? capitalizeFirstLetter(seriesStatus) : action?.name || fallbackName || ''
    const iconSizePx = iconSize === IconSize.Large ? 14 : iconSize === IconSize.Medium ? 12 : 10

    return (
        <Row className="insights-label" wrap={false}>
            <Col style={{ display: 'flex', alignItems: 'center' }} flex="auto">
                {!(hasMultipleSeries && !breakdownValue) && !hideIcon && (
                    <div
                        className="color-icon"
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
                <div className={allowWrap ? '' : 'protect-width'}>
                    {showEventName && (
                        <>
                            {useCustomName && action ? (
                                <EntityFilterInfo filter={action} />
                            ) : (
                                <PropertyKeyInfo disableIcon disablePopover value={eventName} ellipsis={!allowWrap} />
                            )}
                        </>
                    )}

                    {((action?.math && action.math !== 'total') || showCountedByTag) && (
                        <MathTag math={action?.math} mathProperty={action?.math_property} />
                    )}

                    {breakdownValue && !hideBreakdown && (
                        <>
                            {hasMultipleSeries && <span style={{ padding: '0 2px' }}>-</span>}
                            {breakdownValue === 'total' ? <i>Total</i> : breakdownValue}
                        </>
                    )}
                </div>
            </Col>
            <Col flex="none">
                <span className="value">{value}</span>
            </Col>
        </Row>
    )
}
