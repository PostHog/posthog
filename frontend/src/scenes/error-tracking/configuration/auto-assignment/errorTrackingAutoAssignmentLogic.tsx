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

export const errorTrackingAutoAssignmentLogic = kea<errorTrackingAutoAssignmentLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingAutoAssignmentLogic']),

    loaders(({ values }) => ({
        assignmentRules: [
            [] as ErrorTrackingAssignmentRule[],
            {
                loadRules: async () => {
                    return await api.errorTracking.assignmentRules()
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
                createRule: async (rule) => {
                    if (rule.id === 'new') {
                        const createdRule = await api.errorTracking.createAssignmentRule(rule)
                        const newValues = [...values.assignmentRules]
                        return newValues.map((r) => (rule.id === 'new' ? createdRule : r))
                    }
                    return values.assignmentRules
                },
                updateRule: async (rule) => {
                    await api.errorTracking.updateAssignmentRule(rule)
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
        assignmentRulesWithNew: [
            (s) => [s.assignmentRules],
            (assignmentRules): ErrorTrackingAssignmentRule[] => {
                return assignmentRules.length > 0
                    ? assignmentRules
                    : [
                          {
                              id: 'new',
                              assignee: null,
                              filters: { type: FilterLogicalOperator.Or, values: [] },
                          },
                      ]
            },
        ],

        hasNewRule: [
            (s) => [s.assignmentRulesWithNew],
            (assignmentRulesWithNew) => assignmentRulesWithNew.some(({ id }) => id === 'new'),
        ],
    }),
])
