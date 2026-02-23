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

const LOCAL_EVAL_DOCS = [
    {
        label: 'Learn more',
        url: 'https://posthog.com/docs/feature-flags/local-evaluation#restriction-on-local-evaluation',
    },
]

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
        trigger: (context) =>
            context.filters.groups.some((group) =>
                (group.properties ?? []).some(
                    (property) =>
                        property.type === PropertyFilterType.Cohort ||
                        !INSTANTLY_AVAILABLE_PROPERTIES.includes(property.key || '')
                )
            ),
        summary: 'Non-instant properties',
        description:
            "These properties aren't immediately available on first page load for unidentified persons. This feature flag requires that at least one event is sent prior to becoming available to your product or website.",
        severity: 'info',
        docs: [
            {
                label: 'Learn more about how to make feature flags available instantly',
                url: 'https://posthog.com/docs/feature-flags/bootstrapping',
            },
        ],
    },
    {
        id: 'is-not-set-operator',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) => isPropertyFilterWithOperator(property) && property.operator === 'is_not_set'
            ),
        summary: 'is_not_set operator',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: is_not_set operator. The flag will still evaluate correctly when not using local evaluation.',
        severity: 'warning',

        docs: LOCAL_EVAL_DOCS,
    },
    {
        id: 'static-cohort',
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
        summary: 'Static cohorts',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: static cohorts. The flag will still evaluate correctly when not using local evaluation.',
        severity: 'warning',

        docs: LOCAL_EVAL_DOCS,
    },
    {
        id: 'regex-lookahead',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) =>
                    isPropertyFilterWithOperator(property) &&
                    property.operator === 'regex' &&
                    REGEX_LOOKAHEAD.test(String(property.value))
            ),
        summary: 'Lookahead in regex',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: lookahead in regex. The flag will still evaluate correctly when not using local evaluation.',
        severity: 'warning',

        docs: LOCAL_EVAL_DOCS,
    },
    {
        id: 'regex-lookbehind',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) =>
                    isPropertyFilterWithOperator(property) &&
                    property.operator === 'regex' &&
                    REGEX_LOOKBEHIND.test(String(property.value))
            ),
        summary: 'Lookbehind in regex',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: lookbehind in regex. The flag will still evaluate correctly when not using local evaluation.',
        severity: 'warning',

        docs: LOCAL_EVAL_DOCS,
    },
    {
        id: 'regex-backreferences',
        trigger: (context) =>
            isServerEvaluable(context) &&
            allProperties(context).some(
                (property) =>
                    isPropertyFilterWithOperator(property) &&
                    property.operator === 'regex' &&
                    REGEX_BACKREFERENCE.test(String(property.value))
            ),
        summary: 'Backreferences in regex',
        description:
            'This flag cannot be locally evaluated by server-side SDKs due to unsupported features: backreferences in regex. The flag will still evaluate correctly when not using local evaluation.',
        severity: 'warning',

        docs: LOCAL_EVAL_DOCS,
    },
]
