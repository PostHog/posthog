import React from 'react'
import { Tag } from 'antd'
import { ActionFilter } from '~/types'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { operatorMap, capitalizeFirstLetter } from 'lib/utils'
import './InsightLabel.scss'
import { MATHS } from 'lib/constants'

// InsightsLabel pretty prints the action (or event) returned from /insights
interface InsightsLabelProps {
    propertyValue: string
    action: ActionFilter
    value?: string // Show inline value in bold
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

export function InsightLabel({ propertyValue, action, showCountedByTag, value }: InsightsLabelProps): JSX.Element {
    return (
        <div className="insights-label">
            <PropertyKeyInfo disableIcon value={propertyValue} />
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
