import React from 'react'
import { ActionFilter } from '~/types'
import { operatorMap } from '~/lib/utils'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import './TooltipItem.scss'

interface TooltipItemProps {
    propertyValue: string
    action: ActionFilter
    value: string
}

export default function TooltipItem({ propertyValue, action, value }: TooltipItemProps): JSX.Element {
    return (
        <div className="tooltip-item">
            <PropertyKeyInfo disableIcon value={propertyValue} />
            {action.math === 'dau' && ` (Unique users)`}
            {['sum', 'avg', 'min', 'max', 'median', 'p90', 'p95', 'p99'].includes(action.math || '') &&
                action.math_property && (
                    <span>
                        {' ('}
                        {action.math + ' of '}
                        <PropertyKeyInfo disableIcon value={action.math_property} />
                        {')'}
                    </span>
                )}
            {action.properties?.length > 0 && (
                <span>
                    {' ('}
                    {action.properties?.map((property, i, arr) => (
                        <span key={i}>
                            {property.key && `${property.key} `}
                            {operatorMap[property.operator || 'exact'].split(' ')[0]} {property.value}
                            {i !== arr.length - 1 && ', '}
                        </span>
                    ))}
                    {')'}
                </span>
            )}
            <br />
            <span className="value-large">{value}</span>
        </div>
    )
}
