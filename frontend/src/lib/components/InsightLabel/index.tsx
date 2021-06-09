import React from 'react'
import { Tag } from 'antd'
import { ActionFilter } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { operatorMap, capitalizeFirstLetter, alphabet } from 'lib/utils'
import './InsightLabel.scss'
import { MATHS } from 'lib/constants'

// InsightsLabel pretty prints the action (or event) returned from /insights
interface InsightsLabelProps {
    action: ActionFilter
    value?: string
    breakdownValue?: string
    fallbackName: string // Name to display for the series if it can be determined from `action`
    hasMultipleSeries?: boolean // Whether the graph has multiple discrete series (not breakdown values)
    showCountedByTag?: boolean // Force 'counted by' tag to show (always shown when action.math is set)
}

function MathTag({ math, mathProperty }: Record<string, string | undefined>): JSX.Element {
    if (!math || math === 'total') {
        return <Tag>Total</Tag>
    }
    if (math === 'dau') {
        return <Tag>Unique users</Tag>
    }
    if (math && ['sum', 'avg', 'min', 'max', 'median', 'p90', 'p95', 'p99'].includes(math || '')) {
        return (
            <Tag>
                {MATHS[math]?.name || capitalizeFirstLetter(math)}
                {mathProperty && (
                    <>
                        {' of '}
                        <PropertyKeyInfo disableIcon value={mathProperty} />
                    </>
                )}
            </Tag>
        )
    }
    return <Tag>{capitalizeFirstLetter(math)}</Tag>
}

export function InsightLabel({
    action,
    value,
    breakdownValue,
    fallbackName,
    hasMultipleSeries,
    showCountedByTag,
}: InsightsLabelProps): JSX.Element {
    const showEventName = !breakdownValue || hasMultipleSeries
    return (
        <div className="insights-label">
            {hasMultipleSeries && action.order !== undefined && (
                <span className="graph-series-letter">{alphabet[action.order]}</span>
            )}
            {showEventName && <PropertyKeyInfo disableIcon value={action.name || fallbackName} />}
            {breakdownValue && (
                <>
                    {hasMultipleSeries && <span style={{ padding: '0 2px' }}>-</span>}
                    {breakdownValue === 'total' ? <i>Total</i> : breakdownValue}
                </>
            )}

            {((action.math && action.math !== 'total') || showCountedByTag) && (
                <MathTag math={action.math} mathProperty={action.math_property} />
            )}
            {action.properties?.length > 0 && (
                <span>
                    {action.properties?.map((property, i) => (
                        <Tag key={i}>
                            {property.key && <PropertyKeyInfo disableIcon value={property.key} />}{' '}
                            {operatorMap[property.operator || 'exact'].split(' ')[0]} {property.value}
                        </Tag>
                    ))}
                </span>
            )}
            <span className="value">{value}</span>
        </div>
    )
}
