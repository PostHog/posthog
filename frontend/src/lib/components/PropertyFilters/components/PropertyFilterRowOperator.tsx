import clsx from 'clsx'

import { FilterLogicalOperator } from '~/types'

import { OperandTag } from './OperandTag'

export interface PropertyFilterRowOperatorProps {
    index: number
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    hasKey?: boolean
}

export function PropertyFilterRowOperator({
    index,
    orFiltering,
    propertyGroupType,
    hasKey,
}: PropertyFilterRowOperatorProps): JSX.Element {
    const content = orFiltering ? (
        propertyGroupType && index !== 0 && hasKey ? (
            <OperandTag operand={propertyGroupType === FilterLogicalOperator.And ? 'and' : 'or'} />
        ) : null
    ) : index === 0 ? (
        <>
            <span className="TaxonomicPropertyFilter__row-arrow">&#8627;</span>
            <span>where</span>
        </>
    ) : hasKey ? (
        <OperandTag operand="and" />
    ) : null

    return (
        <div
            className={clsx(
                'TaxonomicPropertyFilter__row-operator',
                !content && 'TaxonomicPropertyFilter__row-operator--empty'
            )}
        >
            {content ? <div className="flex items-center gap-1">{content}</div> : null}
        </div>
    )
}
