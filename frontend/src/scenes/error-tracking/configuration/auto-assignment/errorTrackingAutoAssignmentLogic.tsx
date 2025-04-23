import { kea, path, selectors } from 'kea'
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

// const validRule = (rule: ErrorTrackingAssignmentRule): boolean => {
//     return rule.assignee !== null && rule.filters.values.length > 0
// }

export const errorTrackingAutoAssignmentLogic = kea<errorTrackingAutoAssignmentLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingAutoAssignmentLogic']),

    loaders(({ values }) => ({
        assignmentRules: [
            [
                {
                    id: 'new',
                    assignee: null,
                    filters: { type: FilterLogicalOperator.Or, values: [] },
                },
            ] as ErrorTrackingAssignmentRule[],
            {
                loadRules: async () => {
                    const res = await api.errorTracking.assignmentRules()
                    const rules = res.results
                    if (rules.length === 0) {
                        rules.push({
                            id: 'new',
                            assignee: null,
                            filters: { type: FilterLogicalOperator.Or, values: [] },
                        })
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

    selectors({
        hasNewRule: [(s) => [s.assignmentRules], (assignmentRules) => assignmentRules.some(({ id }) => id === 'new')],
    }),
])
