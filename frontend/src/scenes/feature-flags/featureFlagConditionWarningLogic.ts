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

                const unsupportedRegexFeatures = new Set<string>()
                const localEvaluationIssues = new Set<string>()

                properties.forEach((property) => {
                    if (isPropertyFilterWithOperator(property) && property.operator === 'is_not_set') {
                        localEvaluationIssues.add('is_not_set operator')
                    }

                    if (property.type === PropertyFilterType.Cohort) {
                        const cohortId = property.value
                        const cohort = cohortsById[cohortId]
                        if (cohort?.is_static) {
                            localEvaluationIssues.add('static cohorts')
                        }
                    }

                    if (isPropertyFilterWithOperator(property) && property.operator === 'regex') {
                        const pattern = String(property.value)

                        if (REGEX_LOOKAHEAD.test(pattern)) {
                            unsupportedRegexFeatures.add('lookahead')
                        }

                        if (REGEX_LOOKBEHIND.test(pattern)) {
                            unsupportedRegexFeatures.add('lookbehind')
                        }

                        if (REGEX_BACKREFERENCE.test(pattern)) {
                            unsupportedRegexFeatures.add('backreferences')
                        }
                    }
                })

                if (unsupportedRegexFeatures.size > 0) {
                    return `This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (${Array.from(unsupportedRegexFeatures).join(', ')}).`
                }

                if (localEvaluationIssues.size > 0) {
                    return `This flag cannot be evaluated in client environments. It uses: ${Array.from(localEvaluationIssues).join(', ')}.`
                }

                return undefined
            },
        ],
    }),
])
