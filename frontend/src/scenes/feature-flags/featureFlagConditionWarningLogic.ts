import { kea, key, path, props, selectors } from 'kea'

import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter, FeatureFlagEvaluationRuntime } from '~/types'

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

    selectors({
        warning: [
            (_, p) => [p.properties, p.evaluationRuntime],
            (properties: AnyPropertyFilter[], evaluationRuntime: FeatureFlagEvaluationRuntime): string | undefined => {
                if (evaluationRuntime === FeatureFlagEvaluationRuntime.SERVER) {
                    return
                }

                const unsupportedFeatures = new Set<string>()
                properties.forEach((property) => {
                    if (isPropertyFilterWithOperator(property) && property.operator === 'regex') {
                        const pattern = String(property.value)

                        if (REGEX_LOOKAHEAD.test(pattern)) {
                            unsupportedFeatures.add('lookahead')
                        }

                        if (REGEX_LOOKBEHIND.test(pattern)) {
                            unsupportedFeatures.add('lookbehind')
                        }

                        if (REGEX_BACKREFERENCE.test(pattern)) {
                            unsupportedFeatures.add('backreferences')
                        }
                    }
                })

                return unsupportedFeatures.size > 0
                    ? `This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (${Array.from(unsupportedFeatures).join(', ')}).`
                    : undefined
            },
        ],
    }),
])
