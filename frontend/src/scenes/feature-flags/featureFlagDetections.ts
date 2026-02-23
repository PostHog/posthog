import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { INSTANTLY_AVAILABLE_PROPERTIES } from 'lib/constants'

import type { DetectionEntry } from '~/lib/components/HogSense'
import {
    AnyPropertyFilter,
    CohortType,
    FeatureFlagEvaluationRuntime,
    FeatureFlagType,
    PropertyFilterType,
} from '~/types'

const REGEX_LOOKAHEAD = /(?<!\\)\(\?[=!]/
const REGEX_LOOKBEHIND = /(?<!\\)\(\?<[=!]/
const REGEX_BACKREFERENCE = /(?<!\\)\\[1-9]/

export type FeatureFlagDetectionContext = FeatureFlagType & {
    _cohortsById: Partial<Record<string | number, CohortType>>
}

function isServerEvaluable(context: FeatureFlagDetectionContext): boolean {
    return context.evaluation_runtime !== FeatureFlagEvaluationRuntime.CLIENT
}

function allProperties(context: FeatureFlagDetectionContext): AnyPropertyFilter[] {
    return context.filters.groups.flatMap((group) => group.properties ?? [])
}

export const featureFlagDetections: DetectionEntry<FeatureFlagDetectionContext>[] = [
    {
        id: 'non-instant-properties',
        severity: 'info',
        trigger: (context) =>
            context.filters.groups.some((group) =>
                (group.properties ?? []).some(
                    (property) =>
                        property.type === PropertyFilterType.Cohort ||
                        !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
                )
            ),
    },
    {
        id: 'is-not-set-operator',
        severity: 'warning',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) => isPropertyFilterWithOperator(property) && property.operator === 'is_not_set'
            ),
    },
    {
        id: 'static-cohort',
        severity: 'warning',
        trigger: (context) => {
            if (!isServerEvaluable(context)) {
                return false
            }
            const cohortsById = context._cohortsById
            return allProperties(context).some((property) => {
                if (property.type !== PropertyFilterType.Cohort) {
                    return false
                }
                const cohortId = property.value
                const cohort = cohortsById[cohortId] ?? cohortsById[String(cohortId)]
                return cohort?.is_static === true
            })
        },
    },
    {
        id: 'regex-lookahead',
        severity: 'warning',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) =>
                    isPropertyFilterWithOperator(property) &&
                    property.operator === 'regex' &&
                    REGEX_LOOKAHEAD.test(String(property.value))
            ),
    },
    {
        id: 'regex-lookbehind',
        severity: 'warning',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) =>
                    isPropertyFilterWithOperator(property) &&
                    property.operator === 'regex' &&
                    REGEX_LOOKBEHIND.test(String(property.value))
            ),
    },
    {
        id: 'regex-backreferences',
        severity: 'warning',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) =>
                    isPropertyFilterWithOperator(property) &&
                    property.operator === 'regex' &&
                    REGEX_BACKREFERENCE.test(String(property.value))
            ),
    },
]
