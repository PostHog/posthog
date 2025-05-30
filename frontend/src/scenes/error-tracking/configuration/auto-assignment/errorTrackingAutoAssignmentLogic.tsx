import { actions, kea, listeners, path, reducers, selectors } from 'kea'
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

    actions({
        addRule: true,
        setRuleEditable: (id: ErrorTrackingAssignmentRule['id']) => ({ id }),
        unsetRuleEditable: (id: ErrorTrackingAssignmentRule['id']) => ({ id }),
        updateLocalRule: (rule: ErrorTrackingAssignmentRule) => ({ rule }),
        _setLocalRules: (rules: ErrorTrackingAssignmentRule[]) => ({ rules }),
    }),

    reducers({
        localRules: [[] as ErrorTrackingAssignmentRule[], { _setLocalRules: (_, { rules }) => rules }],
        initialLoadComplete: [
            false,
            {
                loadRules: () => false,
                loadRulesSuccess: () => true,
                loadRulesFailure: () => true,
            },
        ],
    }),

    loaders(({ values }) => ({
        assignmentRules: [
            [] as ErrorTrackingAssignmentRule[],
            {
                loadRules: async () => {
                    const { results: rules } = await api.errorTracking.assignmentRules()
                    return rules
                },
                saveRule: async (id) => {
                    const rule = values.localRules.find((r) => r.id === id)
                    const newValues = [...values.assignmentRules]
                    if (rule) {
                        if (rule.id === 'new') {
                            const newRule = await api.errorTracking.createAssignmentRule(rule)
                            return [...newValues, newRule]
                        }
                        await api.errorTracking.updateAssignmentRule(rule)
                        return newValues.map((r) => (r.id === rule.id ? rule : r))
                    }
                    return newValues
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

    listeners(({ values, actions }) => ({
        addRule: () => {
            actions._setLocalRules([
                ...values.localRules,
                {
                    id: 'new',
                    assignee: null,
                    filters: { type: FilterLogicalOperator.Or, values: [] },
                },
            ])
        },
        saveRuleSuccess: ({ payload: id }) => {
            const localRules = [...values.localRules]
            const newEditingRules = localRules.filter((v) => v.id !== id)
            actions._setLocalRules(newEditingRules)
        },
        deleteRuleSuccess: ({ payload: id }) => {
            const localRules = [...values.localRules]
            const newEditingRules = localRules.filter((v) => v.id !== id)
            actions._setLocalRules(newEditingRules)
        },
        setRuleEditable: ({ id }) => {
            const rule = values.assignmentRules.find((r) => r.id === id)
            if (rule) {
                actions._setLocalRules([...values.localRules, rule])
            }
        },
        unsetRuleEditable: ({ id }) => {
            const newLocalRules = [...values.localRules]
            const index = newLocalRules.findIndex((r) => r.id === id)
            if (index >= 0) {
                newLocalRules.splice(index, 1)
                actions._setLocalRules(newLocalRules)
            }
        },
        updateLocalRule: ({ rule }) => {
            const newEditingRules = [...values.localRules]
            const index = newEditingRules.findIndex((r) => r.id === rule.id)

            if (index >= 0) {
                newEditingRules.splice(index, 1, rule)
                actions._setLocalRules(newEditingRules)
            }
        },
    })),

    selectors({
        allRules: [
            (s) => [s.localRules, s.assignmentRules],
            (localRules, assignmentRules): ErrorTrackingAssignmentRule[] =>
                Array.from(new Map([...assignmentRules, ...localRules].map((item) => [item.id, item])).values()),
        ],
        hasNewRule: [(s) => [s.allRules], (allRules): boolean => allRules.some((r) => r.id === 'new')],
    }),
])
