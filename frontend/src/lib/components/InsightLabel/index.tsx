import React from 'react'
import { Tag } from 'antd'
import { ActionFilter } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { capitalizeFirstLetter, hexToRGBA } from 'lib/utils'
import './InsightLabel.scss'
import { MATHS } from 'lib/constants'
import { SeriesLetter } from '../SeriesLetter'

// InsightsLabel pretty prints the action (or event) returned from /insights
interface InsightsLabelProps {
    action: ActionFilter
    seriesColor: string
    value?: string
    breakdownValue?: string
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
    action,
    seriesColor,
    value,
    breakdownValue,
    seriesStatus,
    fallbackName,
    hasMultipleSeries,
    showCountedByTag,
}: InsightsLabelProps): JSX.Element {
    const showEventName = !breakdownValue || hasMultipleSeries
    const eventName = seriesStatus ? capitalizeFirstLetter(seriesStatus) : action.name || fallbackName || ''

    return (
        <div className="insights-label">
            {!(hasMultipleSeries && !breakdownValue) && (
                <div
                    className="color-icon"
                    style={{
                        background: seriesColor,
                        boxShadow: `0px 0px 0px 1px ${hexToRGBA(seriesColor, 0.5)}`,
                    }}
                />
            )}
            {hasMultipleSeries && action.order !== undefined && (
                <SeriesLetter seriesIndex={action.order} seriesColor={seriesColor} hasBreakdown={!!breakdownValue} />
            )}
            {showEventName && <PropertyKeyInfo disableIcon value={eventName} />}

            {hasMultipleSeries && ((action.math && action.math !== 'total') || showCountedByTag) && (
                <MathTag math={action.math} mathProperty={action.math_property} />
            )}

            {breakdownValue && (
                <>
                    {hasMultipleSeries && <span style={{ padding: '0 2px' }}>-</span>}
                    {breakdownValue === 'total' ? <i>Total</i> : breakdownValue}
                </>
            )}

            <span className="value">{value}</span>
        </div>
    )
}
