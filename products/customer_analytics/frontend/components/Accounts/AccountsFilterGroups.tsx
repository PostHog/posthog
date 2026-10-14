import { useActions, useValues } from 'kea'
import { Fragment, useId, useState } from 'react'

import { IconFilter, IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCard, LemonDivider } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { AnyPropertyFilter } from '~/types'

import { AccountRelationshipOperatorValueSelect } from './AccountRelationshipOperatorValueSelect'
import { accountsColumnConfigLogic } from './accountsColumnConfigLogic'
import { accountsLogic } from './accountsLogic'
import {
    ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
    ACCOUNT_FILTER_OPERATOR_ALLOWLIST,
    accountFilterStaticValueOptions,
    isAccountRelationshipFilter,
    type AccountFilter,
} from './accountsPropertyFilters'

export function AccountsFilterGroups(): JSX.Element {
    const { accountFilters, accountFilterGroups } = useValues(accountsLogic)
    const {
        updateAccountFilters,
        addAccountFilterGroup,
        removeFirstAccountFilterGroup,
        removeAccountFilterGroup,
        updateAccountFilterGroup,
    } = useActions(accountsLogic)
    const { customPropertyTaxonomicOptions, relationshipTaxonomicOptions } = useValues(accountsColumnConfigLogic)
    const detailsId = useId()
    const [expanded, setExpanded] = useState(false)
    const groups = [accountFilters, ...accountFilterGroups]
    const count = groups.reduce((total, group) => total + group.length, 0)
    const hasGroups = count > 0 || accountFilterGroups.length > 0
    function renderFilters(filters: AccountFilter[], groupIndex: number): JSX.Element {
        return (
            <PropertyFilters
                propertyFilters={filters as AnyPropertyFilter[]}
                onChange={(updatedFilters) => {
                    setExpanded(true)
                    if (groupIndex === 0) {
                        updateAccountFilters(updatedFilters as AccountFilter[])
                    } else {
                        updateAccountFilterGroup(groupIndex - 1, updatedFilters as AccountFilter[])
                    }
                }}
                pageKey={`customer-analytics-accounts-custom-properties-${groupIndex}`}
                taxonomicGroupTypes={[
                    TaxonomicFilterGroupType.AccountFields,
                    TaxonomicFilterGroupType.AccountRelationships,
                    TaxonomicFilterGroupType.AccountCustomProperties,
                ]}
                taxonomicFilterOptionsFromProp={{
                    [TaxonomicFilterGroupType.AccountFields]: ACCOUNT_FIELD_TAXONOMIC_OPTIONS,
                    [TaxonomicFilterGroupType.AccountRelationships]: relationshipTaxonomicOptions,
                    [TaxonomicFilterGroupType.AccountCustomProperties]: customPropertyTaxonomicOptions,
                }}
                operatorAllowlist={ACCOUNT_FILTER_OPERATOR_ALLOWLIST}
                staticValueOptions={accountFilterStaticValueOptions}
                renderOperatorValueSelect={(filter, onChange) =>
                    isAccountRelationshipFilter(filter) ? (
                        <AccountRelationshipOperatorValueSelect filter={filter} onChange={onChange} />
                    ) : null
                }
                buttonSize="small"
                buttonText={hasGroups ? 'Add condition' : 'Filter'}
                showConditionBadge
                hasRowOperator
            />
        )
    }

    if (!hasGroups) {
        return renderFilters(accountFilters, 0)
    }

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconFilter />}
                active={expanded}
                aria-expanded={expanded}
                aria-controls={expanded ? detailsId : undefined}
                onClick={() => setExpanded(!expanded)}
                data-attr="accounts-toggle-filter-groups"
            >
                <span className="flex items-center gap-2">
                    <span>Filters</span>
                    <LemonBadge.Number count={count} maxDigits={3} status="primary" />
                </span>
            </LemonButton>
            {expanded && (
                <LemonCard
                    hoverEffect={false}
                    className="w-full min-w-0 order-last p-2 bg-surface-secondary"
                    data-attr="accounts-filter-details"
                >
                    <div id={detailsId} className="flex flex-col gap-2">
                        {groups.map((filters, groupIndex) => (
                            <Fragment key={groupIndex}>
                                {groupIndex > 0 && (
                                    <div className="flex items-center gap-2" aria-label="OR">
                                        <LemonDivider className="flex-1 my-0" />
                                        <span className="text-xs font-semibold text-muted">OR</span>
                                        <LemonDivider className="flex-1 my-0" />
                                    </div>
                                )}
                                <LemonCard
                                    hoverEffect={false}
                                    className="p-2 min-w-0 flex items-start gap-2"
                                    data-attr="accounts-filter-group"
                                >
                                    <div className="flex-1 min-w-0">{renderFilters(filters, groupIndex)}</div>
                                    <LemonButton
                                        size="xsmall"
                                        icon={<IconTrash />}
                                        aria-label={`Remove group ${String.fromCharCode(65 + groupIndex)}`}
                                        tooltip="Remove group"
                                        onClick={() =>
                                            groupIndex === 0
                                                ? removeFirstAccountFilterGroup()
                                                : removeAccountFilterGroup(groupIndex - 1)
                                        }
                                        data-attr="accounts-remove-or-group"
                                    />
                                </LemonCard>
                            </Fragment>
                        ))}
                        <LemonButton
                            type="tertiary"
                            size="small"
                            className="self-start"
                            icon={<IconPlusSmall />}
                            onClick={addAccountFilterGroup}
                            disabledReason={
                                groups.some((group) => group.length === 0)
                                    ? 'Add a condition to each group first'
                                    : groups.length >= 10
                                      ? 'You can add up to 10 groups'
                                      : undefined
                            }
                            data-attr="accounts-add-or-group"
                        >
                            Add OR group
                        </LemonButton>
                    </div>
                </LemonCard>
            )}
        </>
    )
}
