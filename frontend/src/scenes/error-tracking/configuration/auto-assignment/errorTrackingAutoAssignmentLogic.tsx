import { kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFiltersGroup } from '~/types'

import type { errorTrackingAutoAssignmentLogicType } from './errorTrackingAutoAssignmentLogicType'

export type ErrorTrackingAssignmentRule = {
    id: string
    assignee: ErrorTrackingIssueAssignee | null
    filters: UniversalFiltersGroup
}

const DEFAULT_ASSIGNMENT_RULE = {
    id: 'new',
    assignee: null,
    filters: { type: FilterLogicalOperator.Or, values: [] },
}

export const errorTrackingAutoAssignmentLogic = kea<errorTrackingAutoAssignmentLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingAutoAssignmentLogic']),
    props({} as { newRuleIfNone: boolean }),

    loaders(({ props, values }) => ({
        assignmentRules: [
            [DEFAULT_ASSIGNMENT_RULE] as ErrorTrackingAssignmentRule[],
            {
                loadRules: async () => {
                    const { results: rules } = await api.errorTracking.assignmentRules()
                    if (rules.length === 0 && props.newRuleIfNone) {
                        return [DEFAULT_ASSIGNMENT_RULE]
                    }
                    return rules
                },
                addRule: async () => {
                    return [
                        ...values.assignmentRules,
                        {
                            id: 'new',
                            assignee: null,
                            filters: { type: FilterLogicalOperator.Or, values: [] },
                        },
                    ]
                },
                saveRule: async (rule) => {
                    const newValues = [...values.assignmentRules]
                    if (rule.id === 'new') {
                        const newRule = await api.errorTracking.createAssignmentRule(rule)
                        return newValues.map((r) => (rule.id === r.id ? newRule : r))
                    }
                    await api.errorTracking.updateAssignmentRule(rule)

                    return newValues
                },
                updateRule: async (rule) => {
                    const newValues = [...values.assignmentRules]
                    return newValues.map((r) => (rule.id === r.id ? rule : r))
                },
                deleteRule: async (id) => {
                    if (id != 'new') {
                        await api.errorTracking.deleteAssignmentRule(id)
                    }
                    const newValues = [...values.assignmentRules]
                    return newValues.filter((v) => v.id !== id)
                },
            },
        ],
    })),

    reducers({
        loadingAllRules: [
            true,
            {
                loadRules: () => true,
                loadRulesSuccess: () => false,
                loadRulesFailure: () => false,
            },
        ],
    }),

    selectors({
        hasNewRule: [(s) => [s.assignmentRules], (assignmentRules) => assignmentRules.some(({ id }) => id === 'new')],
    }),
])
