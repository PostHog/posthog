import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

import { FunnelCorrelation, InsightLogicProps } from '~/types'

import type { funnelCorrelationDetailsLogicType } from './funnelCorrelationDetailsLogicType'
import { funnelDataLogic } from './funnelDataLogic'

export const funnelCorrelationDetailsLogic = kea<funnelCorrelationDetailsLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('insight_funnel')),
    path((key) => ['scenes', 'funnels', 'funnelCorrelationDetailsLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [funnelDataLogic(props), ['steps']],
    })),

    actions({
        openCorrelationDetailsModal: (payload: FunnelCorrelation) => ({ payload }),
        closeCorrelationDetailsModal: true,
    }),

    reducers({
        correlationDetailsModalOpen: [
            false,
            {
                openCorrelationDetailsModal: () => true,
                closeCorrelationDetailsModal: () => false,
            },
        ],
        correlationDetails: [
            null as null | FunnelCorrelation,
            {
                openCorrelationDetailsModal: (_, { payload }) => payload,
            },
        ],
    }),

    selectors({
        correlationMatrixAndScore: [
            (s) => [s.correlationDetails, s.steps],
            (
                correlationDetails,
                steps
            ): {
                truePositive: number
                falsePositive: number
                trueNegative: number
                falseNegative: number
                correlationScore: number
                correlationScoreStrength: 'weak' | 'moderate' | 'strong' | null
            } => {
                if (!correlationDetails || steps.length === 0) {
                    return {
                        truePositive: 0,
                        falsePositive: 0,
                        trueNegative: 0,
                        falseNegative: 0,
                        correlationScore: 0,
                        correlationScoreStrength: null,
                    }
                }

                const successTotal = steps[steps.length - 1].count
                const failureTotal = steps[0].count - successTotal
                const success = correlationDetails.success_count
                const failure = correlationDetails.failure_count

                const truePositive = success // has property, converted
                const falseNegative = failure // has property, but dropped off
                const trueNegative = failureTotal - failure // doesn't have property, dropped off
                const falsePositive = successTotal - success // doesn't have property, converted

                // Phi coefficient: https://en.wikipedia.org/wiki/Phi_coefficient
                const correlationScore =
                    (truePositive * trueNegative - falsePositive * falseNegative) /
                    Math.sqrt(
                        (truePositive + falsePositive) *
                            (truePositive + falseNegative) *
                            (trueNegative + falsePositive) *
                            (trueNegative + falseNegative)
                    )

                const correlationScoreStrength =
                    Math.abs(correlationScore) > 0.5 ? 'strong' : Math.abs(correlationScore) > 0.3 ? 'moderate' : 'weak'

                return {
                    correlationScore,
                    truePositive,
                    falsePositive,
                    trueNegative,
                    falseNegative,
                    correlationScoreStrength,
                }
            },
        ],
    }),
])
