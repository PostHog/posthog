import { MemberSelectMultiple } from 'lib/components/MemberSelectMultiple'
import { OperatorSelect } from 'lib/components/PropertyFilters/components/OperatorValueSelect'
import { isOperatorFlag } from 'lib/utils/operators'

import { PropertyFilterValue, PropertyOperator } from '~/types'

import type { AccountRelationshipFilter } from './accountsPropertyFilters'

const RELATIONSHIP_FILTER_OPERATORS = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IsSet,
    PropertyOperator.IsNotSet,
]

export function AccountRelationshipOperatorValueSelect({
    filter,
    onChange,
}: {
    filter: AccountRelationshipFilter
    onChange: (operator: PropertyOperator, value: PropertyFilterValue) => void
}): JSX.Element {
    const operator = filter.operator ?? PropertyOperator.Exact
    const userIds = (Array.isArray(filter.value) ? filter.value : [filter.value]).filter(
        (value): value is number => typeof value === 'number'
    )

    return (
        <>
            <div data-attr="taxonomic-operator">
                <OperatorSelect
                    operator={operator}
                    operators={RELATIONSHIP_FILTER_OPERATORS}
                    onChange={(nextOperator) => onChange(nextOperator, isOperatorFlag(nextOperator) ? null : userIds)}
                    size="small"
                />
            </div>
            {!isOperatorFlag(operator) && (
                <div className="shrink grow-[1000] min-w-[10rem] overflow-hidden" data-attr="taxonomic-value-select">
                    <MemberSelectMultiple
                        idKey="id"
                        value={userIds}
                        onChange={(users) =>
                            onChange(
                                operator,
                                users.map((user) => user.id)
                            )
                        }
                    />
                </div>
            )}
        </>
    )
}
