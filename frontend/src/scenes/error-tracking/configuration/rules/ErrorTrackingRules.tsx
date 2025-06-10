import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonDialog, LemonSelect, Spinner } from '@posthog/lemon-ui'
import { BindLogic, useActions, useValues } from 'kea'
import { PropertyFilters, PropertyFiltersProps } from 'lib/components/PropertyFilters/PropertyFilters'
import { useEffect } from 'react'
import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from 'scenes/error-tracking/components/Assignee/AssigneeDisplay'
import { AssigneeSelect } from 'scenes/error-tracking/components/Assignee/AssigneeSelect'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { errorTrackingRulesLogic } from './errorTrackingRulesLogic'
import { ErrorTrackingAssignmentRule, ErrorTrackingRule, ErrorTrackingRuleType } from './types'

function ErrorTrackingRules<T extends ErrorTrackingRule>({
    ruleType,
    children,
}: {
    ruleType: ErrorTrackingRuleType
    children: ({ rule, editable }: { rule: T; editable: boolean }) => JSX.Element
}): JSX.Element {
    const logicProps = { ruleType }
    const logic = errorTrackingRulesLogic(logicProps)

    const { allRules, localRules, initialLoadComplete } = useValues(logic)
    const { loadRules } = useActions(logic)

    useEffect(() => {
        loadRules()
    }, [loadRules])

    return !initialLoadComplete ? (
        <Spinner />
    ) : (
        <BindLogic logic={errorTrackingRulesLogic} props={logicProps}>
            <div className="flex flex-col gap-y-2 mt-2">
                {allRules.map((persistedRule) => {
                    const editingRule = localRules.find((r) => r.id === persistedRule.id) as T

                    const editable = !!editingRule
                    const rule = editingRule ?? persistedRule

                    return children({ rule, editable })
                })}

                <AddRuleButton />
            </div>
        </BindLogic>
    )
}

const AddRuleButton = (): JSX.Element | null => {
    const { hasNewRule } = useValues(errorTrackingRulesLogic)
    const { addRule } = useActions(errorTrackingRulesLogic)

    return !hasNewRule ? (
        <div>
            <LemonButton type="primary" size="small" onClick={addRule}>
                Add rule
            </LemonButton>
        </div>
    ) : null
}

const Actions = ({ rule, editable }: { rule: ErrorTrackingRule; editable: boolean }): JSX.Element => {
    const { saveRule, deleteRule, setRuleEditable, unsetRuleEditable } = useActions(errorTrackingRulesLogic)

    return (
        <div className="flex gap-1">
            {editable ? (
                <>
                    {rule.id === 'new' ? null : (
                        <LemonButton
                            size="small"
                            icon={<IconTrash />}
                            status="danger"
                            onClick={() =>
                                LemonDialog.open({
                                    title: 'Delete rule',
                                    description:
                                        'Are you sure you want to delete this rule? This action cannot be undone',
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
                        />
                    )}
                    <LemonButton size="small" onClick={() => unsetRuleEditable(rule.id)}>
                        Cancel
                    </LemonButton>
                    <LemonButton size="small" type="primary" onClick={() => saveRule(rule.id)}>
                        Save
                    </LemonButton>
                </>
            ) : (
                <LemonButton size="small" icon={<IconPencil />} onClick={() => setRuleEditable(rule.id)} />
            )}
        </div>
    )
}

const Filters = ({
    rule,
    editable,
    taxonomicGroupTypes,
    ...props
}: Pick<PropertyFiltersProps, 'taxonomicGroupTypes' | 'propertyAllowList'> & {
    rule: ErrorTrackingRule
    editable: boolean
    taxonomicGroupTypes: PropertyFiltersProps['taxonomicGroupTypes']
    excludedProperties?: PropertyFiltersProps['excludedProperties']
}): JSX.Element => {
    const { updateLocalRule } = useActions(errorTrackingRulesLogic)

    return (
        <PropertyFilters
            editable={editable}
            propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
            taxonomicGroupTypes={taxonomicGroupTypes}
            onChange={(properties: AnyPropertyFilter[]) =>
                updateLocalRule({ ...rule, filters: { ...rule.filters, values: properties } })
            }
            pageKey={`error-tracking-rule-properties-${rule.id}`}
            buttonSize="small"
            propertyGroupType={rule.filters.type}
            hasRowOperator={false}
            disablePopover
            {...props}
        />
    )
}

const Assignee = ({ rule, editable }: { rule: ErrorTrackingAssignmentRule; editable: boolean }): JSX.Element => {
    const { updateLocalRule } = useActions(errorTrackingRulesLogic)

    return editable ? (
        <AssigneeSelect assignee={rule.assignee} onChange={(assignee) => updateLocalRule({ ...rule, assignee })}>
            {(displayAssignee) => (
                <LemonButton fullWidth type="secondary" size="small">
                    <AssigneeLabelDisplay assignee={displayAssignee} placeholder="Choose user" />
                </LemonButton>
            )}
        </AssigneeSelect>
    ) : (
        <AssigneeResolver assignee={rule.assignee}>
            {({ assignee }) => (
                <>
                    <AssigneeIconDisplay assignee={assignee} />
                    <AssigneeLabelDisplay assignee={assignee} />
                </>
            )}
        </AssigneeResolver>
    )
}

const Operator = ({ rule, editable }: { rule: ErrorTrackingRule; editable: boolean }): JSX.Element => {
    const { updateLocalRule } = useActions(errorTrackingRulesLogic)

    const operator = rule.filters.type

    return editable ? (
        <LemonSelect
            size="small"
            value={operator}
            onChange={(type) => updateLocalRule({ ...rule, filters: { ...rule.filters, type } })}
            options={[
                { label: 'All', value: FilterLogicalOperator.And },
                { label: 'Any', value: FilterLogicalOperator.Or },
            ]}
        />
    ) : (
        <span className="font-semibold">{operator === FilterLogicalOperator.And ? 'all' : 'any'}</span>
    )
}

ErrorTrackingRules.Assignee = Assignee
ErrorTrackingRules.Filters = Filters
ErrorTrackingRules.Operator = Operator
ErrorTrackingRules.Actions = Actions

export default ErrorTrackingRules
