import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDivider, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect } from 'react'
import { AssigneeLabelDisplay } from 'scenes/error-tracking/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from 'scenes/error-tracking/components/Assignee/AssigneeSelect'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { errorTrackingAutoAssignmentLogic } from './errorTrackingAutoAssignmentLogic'

export function ErrorTrackingAutoAssignment(): JSX.Element {
    const logic = errorTrackingAutoAssignmentLogic({ newRuleIfNone: true })
    const { assignmentRules, hasNewRule, loadingAllRules } = useValues(logic)
    const { loadRules, addRule, updateRule, deleteRule } = useActions(logic)

    console.log(assignmentRules)

    useEffect(() => {
        loadRules()
    }, [loadRules])

    return loadingAllRules ? (
        <Spinner />
    ) : (
        <div className="flex flex-col gap-y-2 mt-2">
            {assignmentRules.map((rule) => (
                <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                    <div className="flex gap-2 justify-between px-2 py-3">
                        <div className="flex gap-2 items-center">
                            <div>Assign to</div>
                            <AssigneeSelect
                                assignee={rule.assignee}
                                onChange={(assignee) => updateRule({ ...rule, assignee })}
                            >
                                {(displayAssignee) => (
                                    <LemonButton fullWidth type="secondary" size="small">
                                        <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Choose user" />
                                    </LemonButton>
                                )}
                            </AssigneeSelect>
                            <div>when</div>
                            <LemonSelect
                                size="small"
                                value={rule.filters.type}
                                onChange={(type) => updateRule({ ...rule, filters: { ...rule.filters, type } })}
                                options={[
                                    { label: 'All', value: FilterLogicalOperator.And },
                                    { label: 'Any', value: FilterLogicalOperator.Or },
                                ]}
                            />
                            <div>filters match</div>
                        </div>
                        <LemonButton icon={<IconTrash />} onClick={() => deleteRule(rule.id)} />
                    </div>
                    <LemonDivider className="my-0" />
                    <div className="p-2">
                        <PropertyFilters
                            propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                            taxonomicGroupTypes={[TaxonomicFilterGroupType.ErrorTrackingIssues]}
                            onChange={(properties: AnyPropertyFilter[]) =>
                                updateRule({ ...rule, filters: { ...rule.filters, values: properties } })
                            }
                            pageKey={`error-tracking-auto-assignment-properties-${rule.id}`}
                            disablePopover
                            buttonSize="small"
                            excludedProperties={{ [TaxonomicFilterGroupType.ErrorTrackingIssues]: ['assignee'] }}
                            propertyGroupType={rule.filters.type}
                            orFiltering
                        />
                    </div>
                </LemonCard>
            ))}

            <div>
                <LemonButton type="primary" size="small" onClick={addRule}>
                    {`${hasNewRule ? 'Save' : 'Add'} rule`}
                </LemonButton>
            </div>
        </div>
    )
}
