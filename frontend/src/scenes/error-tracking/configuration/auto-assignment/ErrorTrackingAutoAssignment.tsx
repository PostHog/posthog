import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonDialog, LemonDivider, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useEffect } from 'react'
import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from 'scenes/error-tracking/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from 'scenes/error-tracking/components/Assignee/AssigneeSelect'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { type ErrorTrackingAssignmentRule, errorTrackingAutoAssignmentLogic } from './errorTrackingAutoAssignmentLogic'

export function ErrorTrackingAutoAssignment(): JSX.Element {
    const { allRules, initialLoadComplete, localRules, hasNewRule } = useValues(errorTrackingAutoAssignmentLogic)
    const { loadRules, addRule, updateLocalRule, deleteRule, saveRule, setRuleEditable, unsetRuleEditable } =
        useActions(errorTrackingAutoAssignmentLogic)

    useEffect(() => {
        loadRules()
    }, [loadRules])

    if (!initialLoadComplete) {
        return <Spinner />
    }

    return (
        <div className="flex flex-col gap-y-2 mt-2">
            {allRules.map((persistedRule) => {
                const editingRule = localRules.find((r) => r.id === persistedRule.id)

                const editable = !!editingRule
                const rule = editingRule ?? persistedRule

                return (
                    <LemonCard key={rule.id} hoverEffect={false} className="flex flex-col p-0">
                        <div className="flex gap-2 justify-between px-2 py-3">
                            <div className="flex gap-1 items-center">
                                <div>Assign to</div>
                                <RuleAssignee
                                    assignee={rule.assignee}
                                    onChange={(assignee) => updateLocalRule({ ...rule, assignee })}
                                    editable={editable}
                                />
                                <div>when</div>
                                <RuleOperator
                                    operator={rule.filters.type}
                                    onChange={(type) =>
                                        updateLocalRule({ ...rule, filters: { ...rule.filters, type } })
                                    }
                                    editable={editable}
                                />
                                <div>filters match</div>
                            </div>
                            <RuleActions
                                onClickSave={() => saveRule(rule.id)}
                                onClickDelete={
                                    rule.id === 'new'
                                        ? undefined
                                        : () =>
                                              LemonDialog.open({
                                                  title: 'Delete rule',
                                                  description: 'Are you sure you want to delete your assignment rule?',
                                                  primaryButton: {
                                                      status: 'danger',
                                                      children: 'Remove',
                                                      onClick: () => deleteRule(rule.id),
                                                  },
                                                  secondaryButton: {
                                                      children: 'Cancel',
                                                  },
                                              })
                                }
                                onClickEdit={() => setRuleEditable(rule.id)}
                                onClickCancel={() => unsetRuleEditable(rule.id)}
                                editable={editable}
                            />
                        </div>
                        <LemonDivider className="my-0" />
                        <div className="p-2">
                            <PropertyFilters
                                editable={editable}
                                propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                                onChange={(properties: AnyPropertyFilter[]) =>
                                    updateLocalRule({ ...rule, filters: { ...rule.filters, values: properties } })
                                }
                                pageKey={`error-tracking-auto-assignment-properties-${rule.id}`}
                                buttonSize="small"
                                propertyGroupType={rule.filters.type}
                                hasRowOperator={false}
                                disablePopover
                            />
                        </div>
                    </LemonCard>
                )
            })}

            {!hasNewRule && (
                <div>
                    <LemonButton type="primary" size="small" onClick={addRule}>
                        Add rule
                    </LemonButton>
                </div>
            )}
        </div>
    )
}

const RuleAssignee = ({
    assignee,
    editable,
    onChange,
}: {
    assignee: ErrorTrackingAssignmentRule['assignee']
    editable: boolean
    onChange: (assignee: ErrorTrackingIssue['assignee']) => void
}): JSX.Element => {
    return editable ? (
        <AssigneeSelect assignee={assignee} onChange={onChange}>
            {(displayAssignee) => (
                <LemonButton fullWidth type="secondary" size="small">
                    <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Choose user" />
                </LemonButton>
            )}
        </AssigneeSelect>
    ) : (
        <AssigneeResolver assignee={assignee}>
            {({ assignee }) => (
                <>
                    <AssigneeIconDisplay assignee={assignee} />
                    <AssigneeLabelDisplay assignee={assignee} />
                </>
            )}
        </AssigneeResolver>
    )
}

const RuleOperator = ({
    operator,
    onChange,
    editable,
}: {
    operator: FilterLogicalOperator
    onChange: (value: FilterLogicalOperator) => void
    editable: boolean
}): JSX.Element => {
    return editable ? (
        <LemonSelect
            size="small"
            value={operator}
            onChange={onChange}
            options={[
                { label: 'All', value: FilterLogicalOperator.And },
                { label: 'Any', value: FilterLogicalOperator.Or },
            ]}
        />
    ) : (
        <span className="font-semibold">{operator === FilterLogicalOperator.And ? 'all' : 'any'}</span>
    )
}

const RuleActions = ({
    editable,
    onClickSave,
    onClickCancel,
    onClickDelete,
    onClickEdit,
}: {
    editable: boolean
    onClickSave: () => void
    onClickCancel: () => void
    onClickDelete?: () => void
    onClickEdit: () => void
}): JSX.Element => {
    return (
        <div className="flex gap-1">
            {editable ? (
                <>
                    {onClickDelete && (
                        <LemonButton size="small" icon={<IconTrash />} status="danger" onClick={onClickDelete} />
                    )}
                    <LemonButton size="small" onClick={onClickCancel}>
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" onClick={onClickSave}>
                        Save
                    </LemonButton>
                </>
            ) : (
                <LemonButton size="small" icon={<IconPencil />} onClick={onClickEdit} />
            )}
        </div>
    )
}
