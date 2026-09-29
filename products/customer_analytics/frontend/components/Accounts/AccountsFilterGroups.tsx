import { useActions, useValues } from 'kea'
import { Fragment, useState } from 'react'

import { IconPlusSmall, IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonCard, LemonCollapse, LemonDivider, Tooltip } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { formatPropertyLabel, propertyFilterTypeToPropertyDefinitionType } from 'lib/components/PropertyFilters/utils'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Lettermark, LettermarkColor } from 'lib/lemon-ui/Lettermark'

import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
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
    const { formatPropertyValueForDisplay } = useValues(propertyDefinitionsModel)
    const [expanded, setExpanded] = useState(false)
    const groups = [accountFilters, ...accountFilterGroups]
    const count = groups.reduce((total, group) => total + group.length, 0)
    const hasGroups = count > 0 || accountFilterGroups.length > 0
    const summary = groups
        .map((group) => {
            const conditions = group.map((filter) =>
                formatPropertyLabel(
                    filter as AnyPropertyFilter,
                    {},
                    (value) =>
                        formatPropertyValueForDisplay(
                            filter.key,
                            value,
                            propertyFilterTypeToPropertyDefinitionType(filter.type)
                        )?.toString() || '?'
                ).trim()
            )
            return conditions.length > 1 ? `(${conditions.join(' AND ')})` : conditions[0] || 'Incomplete group'
        })
        .join(' OR ')

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
        <LemonCollapse
            className="w-full min-w-0 order-last"
            size="small"
            activeKey={expanded ? 'filters' : null}
            onChange={(key) => setExpanded(key === 'filters')}
            panels={[
                {
                    key: 'filters',
                    dataAttr: 'accounts-toggle-filter-groups',
                    className: 'p-2',
                    header: (
                        <span className="flex items-center gap-2 min-w-0 flex-1">
                            <span>Filters</span>
                            <LemonBadge.Number count={count} maxDigits={3} status="muted" />
                            <Tooltip title={summary}>
                                <span className="truncate text-muted font-normal flex-1 ph-no-capture">{summary}</span>
                            </Tooltip>
                            <span className="text-muted font-normal shrink-0">{expanded ? 'Collapse' : 'Edit'}</span>
                        </span>
                    ),
                    content: (
                        <div className="flex flex-col gap-2 min-w-0">
                            <span className="text-xs text-muted">
                                Search, tags, and assignment filters apply to every group.
                            </span>
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
                                        className="p-2 min-w-0"
                                        data-attr="accounts-filter-group"
                                    >
                                        <div className="flex items-center gap-2 mb-2">
                                            <Lettermark
                                                name={String.fromCharCode(65 + groupIndex)}
                                                color={LettermarkColor.Gray}
                                                size="small"
                                            />
                                            <span className="text-xs text-muted flex-1">Match all conditions</span>
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
                                        </div>
                                        {renderFilters(filters, groupIndex)}
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
                    ),
                },
            ]}
        />
    )
}
