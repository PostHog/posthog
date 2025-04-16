import { LemonButton, LemonCard, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect } from 'react'
import { AssigneeSelect } from 'scenes/error-tracking/AssigneeSelect'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { errorTrackingAutoAssignmentLogic } from './errorTrackingAutoAssignmentLogic'

export function ErrorTrackingAutoAssignment(): JSX.Element {
    const { assignmentRulesWithNew, hasNewRule } = useValues(errorTrackingAutoAssignmentLogic)
    const { loadRules, addRule, updateRule } = useActions(errorTrackingAutoAssignmentLogic)

    useEffect(() => {
        loadRules()
    }, [loadRules])

    return (
        <div className="flex flex-col gap-y-2">
            {assignmentRulesWithNew.map((rule) => (
                <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                    <div className="flex gap-2 items-center px-2 py-3">
                        <div>Assign to</div>
                        <AssigneeSelect
                            showName
                            type="secondary"
                            size="small"
                            unassignedLabel="Choose"
                            assignee={rule.assignee}
                            onChange={(assignee) => updateRule({ ...rule, assignee })}
                        />
                        <div>when</div>
                        <LemonSelect
                            size="small"
                            value={rule.filters.type}
                            onChange={(type) => updateRule({ ...rule, filters: { ...rule, type } })}
                            options={[
                                { label: 'All', value: FilterLogicalOperator.And },
                                { label: 'Any', value: FilterLogicalOperator.Or },
                            ]}
                        />
                        <div>filters match</div>
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="py-2">
                        <PropertyFilters
                            propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.ErrorTrackingIssueProperties]}
                            onChange={(properties: AnyPropertyFilter[]) => {
                                debugger
                                updateRule({ ...rule, filters: { ...rule, values: properties } })
                            }}
                            pageKey={`error-tracking-auto-assignment-properties-${rule.id}`}
                            buttonSize="small"
                            disablePopover
                        />
                    </div>
                </LemonCard>
            ))}

            <div>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={addRule}
                    disabledReason={hasNewRule ? 'Finish creating your new rule first' : undefined}
                >
                    Add rule
                </LemonButton>
            </div>
        </div>
    )
}
