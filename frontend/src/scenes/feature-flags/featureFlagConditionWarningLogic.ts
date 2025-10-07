import { kea, key, path, props, selectors } from 'kea'

import { isPropertyFilterWithOperator } from 'lib/components/PropertyFilters/utils'

import { AnyPropertyFilter, FeatureFlagEvaluationRuntime } from '~/types'

import type { featureFlagConditionWarningLogicType } from './featureFlagConditionWarningLogicType'

export interface FeatureFlagConditionWarningLogicProps {
    properties: AnyPropertyFilter[]
    evaluationRuntime: FeatureFlagEvaluationRuntime
}

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

                        // Check for lookahead assertions: (?= or (?!
                        if (pattern.includes('(?=') || pattern.includes('(?!')) {
                            unsupportedFeatures.add('lookahead')
                        }

                        // Check for lookbehind assertions: (?<= or (?<!
                        if (pattern.includes('(?<=') || pattern.includes('(?<!')) {
                            unsupportedFeatures.add('lookbehind')
                        }

                        // Check for backreferences: \1 through \9
                        if (/\\[1-9]/.test(pattern)) {
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
