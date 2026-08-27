import clsx from 'clsx'

import { FilterLogicalOperator } from '~/types'

import { OperandTag } from './OperandTag'

export interface PropertyFilterRowOperatorProps {
    index: number
    orFiltering?: boolean
    propertyGroupType?: FilterLogicalOperator | null
    /** Or-filtering leaves the gutter empty until the row has a key. */
    hasKey?: boolean
}

/** The fixed-width left gutter every filter row shares, holding "where" or the AND/OR tag.
 * Reserving it for each row is what keeps the rows' controls in one column. */
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

    // Still occupies the gutter when empty, so every row's controls stay in one column. The
    // modifier lets the narrow layout drop it instead, where it would otherwise take a whole
    // wrapped line and push the row's own controls down.
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
