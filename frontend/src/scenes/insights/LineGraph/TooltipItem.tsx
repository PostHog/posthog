import React from 'react'
import { ActionFilter } from '~/types'
import { operatorMap, capitalizeFirstLetter } from '~/lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './TooltipItem.scss'
import { Tag } from 'antd'

interface TooltipItemProps {
    propertyValue: string
    action: ActionFilter
    value: string
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
                {capitalizeFirstLetter(math)}
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

export default function TooltipItem({ propertyValue, action, value, showCountedByTag }: TooltipItemProps): JSX.Element {
    return (
        <div className="tooltip-item">
            <PropertyKeyInfo disableIcon value={propertyValue} />
            {((action.math && action.math !== 'total') || showCountedByTag) && (
                <MathTag math={action.math} mathProperty={action.math_property} />
            )}
            {action.properties?.length > 0 && (
                <span>
                    {' ('}
                    {action.properties?.map((property, i, arr) => (
                        <span key={i}>
                            {property.key && <PropertyKeyInfo disableIcon value={property.key} />}{' '}
                            {operatorMap[property.operator || 'exact'].split(' ')[0]} {property.value}
                            {i !== arr.length - 1 && ', '}
                        </span>
                    ))}
                    {')'}
                </span>
            )}
            <span className="value">{value}</span>
        </div>
    )
}
