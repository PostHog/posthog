import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { experimentLogic } from 'scenes/experiments/experimentLogic'

import type { CachedNewExperimentQueryResponse } from '~/queries/schema/schema-general'
import type { ExperimentIdType } from '~/types'

import type { experimentSummaryLogicType } from './experimentSummaryLogicType'

export function formatExperimentResultsForAI(
    primaryMetrics: CachedNewExperimentQueryResponse[],
    secondaryMetrics: CachedNewExperimentQueryResponse[]
): string {
    const lines: string[] = []

    // Format primary metrics
    if (primaryMetrics.length > 0) {
        lines.push('## Primary Metrics')
        primaryMetrics.forEach((metric, index) => {
            lines.push(`### Metric ${index + 1}`)
            lines.push('```json')
            lines.push(JSON.stringify(metric, null, 2))
            lines.push('```')
            lines.push('')
        })
    }

    // Format secondary metrics
    if (secondaryMetrics.length > 0) {
        lines.push('## Secondary Metrics')
        secondaryMetrics.forEach((metric, index) => {
            lines.push(`### Metric ${index + 1}`)
            lines.push('```json')
            lines.push(JSON.stringify(metric, null, 2))
            lines.push('```')
            lines.push('')
        })
    }

    return lines.join('\n')
}

export interface ExperimentSummaryLogicProps {
    experimentId: ExperimentIdType
}

export const experimentSummaryLogic = kea<experimentSummaryLogicType>([
    path((key) => ['scenes', 'experiments', 'components', 'AISummary', 'experimentSummaryLogic', key]),
    props({} as ExperimentSummaryLogicProps),
    connect((props: ExperimentSummaryLogicProps) => ({
        values: [
            experimentLogic(props),
            [
                'experiment',
                'primaryMetricsResultsLoading',
                'secondaryMetricsResultsLoading',
                'primaryMetricsResults',
                'secondaryMetricsResults',
            ],
        ],
    })),

    actions(() => ({
        generateSummary: true,
        resetSummary: true,
        updateSummary: (chunk: string) => ({ chunk }),
        setGenerating: (generating: boolean) => ({ generating }),
    })),

    reducers(() => ({
        summary: [
            '',
            {
                generateSummary: () => '',
                resetSummary: () => '',
                updateSummary: (_, { chunk }) => chunk,
            },
        ],
        isGenerating: [
            false,
            {
                generateSummary: () => true,
                resetSummary: () => false,
                setGenerating: (_, { generating }) => generating,
            },
        ],
    })),

    selectors(() => ({
        metricsLoading: [
            (state) => [state.primaryMetricsResultsLoading, state.secondaryMetricsResultsLoading],
            (primaryMetricsResultsLoading, secondaryMetricsResultsLoading) =>
                primaryMetricsResultsLoading || secondaryMetricsResultsLoading,
        ],
    })),

    listeners(({ actions, values, props }) => ({
        [experimentLogic(props).actionTypes.setPrimaryMetricsResultsLoading]: ({ loading }) => {
            if (!loading && !values.metricsLoading) {
                actions.generateSummary()
            }
        },
        [experimentLogic(props).actionTypes.setSecondaryMetricsResultsLoading]: ({ loading }) => {
            if (!loading && !values.metricsLoading) {
                actions.generateSummary()
            }
        },
        generateSummary: async () => {
            if (!values.experiment) {
                lemonToast.error('Experiment not found')
                return
            }

            // Get the formatted experiment results data
            const resultsData = formatExperimentResultsForAI(
                values.primaryMetricsResults,
                values.secondaryMetricsResults
            )

            try {
                await api.stream(`/api/environments/@current/max_tools/experiment_results_summary/`, {
                    method: 'POST',
                    data: {
                        experiment_id: props.experimentId.toString(),
                        results_data: resultsData,
                    },
                    onMessage: (event) => {
                        try {
                            const data = JSON.parse(event.data)
                            if (data.content) {
                                actions.updateSummary(data.content)
                            }
                        } catch (e) {
                            lemonToast.error(`Failed to generate summary, ${e}`)
                            actions.setGenerating(false)
                        }
                    },
                    onError: (error) => {
                        lemonToast.error(`Failed to generate summary, ${error}`)
                        actions.setGenerating(false)
                    },
                })
                // cleanup the isGenerating state
                actions.setGenerating(false)
            } catch (error) {
                lemonToast.error(`Failed to generate summary, ${error}`)
                actions.setGenerating(false)
            }
        },
    })),
])
