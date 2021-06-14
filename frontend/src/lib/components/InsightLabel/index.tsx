import React from 'react'
import { Col, Row, Tag } from 'antd'
import { ActionFilter } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, hexToRGBA } from 'lib/utils'
import './InsightLabel.scss'
import { MATHS } from 'lib/constants'
import { SeriesLetter } from '../SeriesLetter'

// InsightsLabel pretty prints the action (or event) returned from /insights
interface InsightsLabelProps {
    seriesColor: string
    action?: ActionFilter
    value?: string
    breakdownValue?: string
    hideBreakdown?: boolean // Whether to hide the breakdown detail in the label
    hideIcon?: boolean // Whether to hide the icon that showcases the color of the series
    seriesStatus?: string // Used by lifecycle chart to display the series name
    fallbackName?: string // Name to display for the series if it can be determined from `action`
    hasMultipleSeries?: boolean // Whether the graph has multiple discrete series (not breakdown values)
    showCountedByTag?: boolean // Force 'counted by' tag to show (always shown when action.math is set)
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
    seriesColor,
    action,
    value,
    breakdownValue,
    hideBreakdown,
    hideIcon,
    seriesStatus,
    fallbackName,
    hasMultipleSeries,
    showCountedByTag,
}: InsightsLabelProps): JSX.Element {
    const showEventName = !breakdownValue || hasMultipleSeries
    const eventName = seriesStatus ? capitalizeFirstLetter(seriesStatus) : action?.name || fallbackName || ''

    return (
        <Row className="insights-label" wrap={false}>
            <Col style={{ display: 'flex', alignItems: 'center' }} flex="auto">
                {!(hasMultipleSeries && !breakdownValue) && !hideIcon && (
                    <div
                        className="color-icon"
                        style={{
                            background: seriesColor,
                            boxShadow: `0px 0px 0px 1px ${hexToRGBA(seriesColor, 0.5)}`,
                        }}
                    />
                )}
                {hasMultipleSeries && action?.order !== undefined && (
                    <SeriesLetter
                        seriesIndex={action.order}
                        seriesColor={seriesColor}
                        hasBreakdown={!!breakdownValue}
                    />
                )}
                <div className="protect-width">
                    {showEventName && <PropertyKeyInfo disableIcon disablePopover value={eventName} />}

                    {hasMultipleSeries && ((action?.math && action.math !== 'total') || showCountedByTag) && (
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
