import { connect, kea, key, path, props, selectors } from 'kea'

import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'
import { cohortsModel } from '~/models/cohortsModel'

import { AnyPropertyFilter, CohortType, FeatureFlagEvaluationRuntime, PropertyFilterType } from '~/types'

import type { featureFlagConditionWarningLogicType } from './featureFlagConditionWarningLogicType'

export interface FeatureFlagConditionWarningLogicProps {
    properties: AnyPropertyFilter[]
    evaluationRuntime: FeatureFlagEvaluationRuntime
}

const REGEX_LOOKAHEAD = /(?<!\\)\(\?[=!]/ // (?= or (?!
const REGEX_LOOKBEHIND = /(?<!\\)\(\?<[=!]/ //  or (?<!
const REGEX_BACKREFERENCE = /(?<!\\)\\[1-9]/ // \1 through \9

export const featureFlagConditionWarningLogic = kea<featureFlagConditionWarningLogicType>([
    path(['scenes', 'feature-flags', 'featureFlagConditionWarningLogic']),
    props({} as FeatureFlagConditionWarningLogicProps),
    key((props) => JSON.stringify(props.properties)),
    connect({
        values: [cohortsModel, ['cohortsById']],
    }),

    selectors({
        warning: [
            (s, p) => [s.cohortsById, p.properties, p.evaluationRuntime],
            (
                cohortsById: Partial<Record<string | number, CohortType>>,
                properties: AnyPropertyFilter[],
                evaluationRuntime: FeatureFlagEvaluationRuntime
            ): string | undefined => {
                if (evaluationRuntime === FeatureFlagEvaluationRuntime.SERVER) {
                    return
                }

                const issues: string[] = []

                properties.forEach((property) => {
                    if (isPropertyFilterWithOperator(property) && property.operator === 'is_not_set') {
                        issues.push('is_not_set operator')
                    }

                    if (property.type === PropertyFilterType.Cohort) {
                        const cohortId = property.value
                        const cohort = cohortsById[cohortId]
                        if (cohort?.is_static) {
                            issues.push('static cohorts')
                        }
                    }

                    if (isPropertyFilterWithOperator(property) && property.operator === 'regex') {
                        const pattern = String(property.value)

                        if (REGEX_LOOKAHEAD.test(pattern)) {
                            issues.push('lookahead in regex')
                        }

                        if (REGEX_LOOKBEHIND.test(pattern)) {
                            issues.push('lookbehind in regex')
                        }

                        if (REGEX_BACKREFERENCE.test(pattern)) {
                            issues.push('backreferences in regex')
                        }
                    }
                })

                if (issues.length === 0) {
                    return undefined
                }

                const uniqueIssues = [...new Set(issues)]

                return `This flag cannot be evaluated locally. Unsupported features: ${uniqueIssues.join(', ')}.`
            },
        ],
    }),
])
