import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import type { ExperimentIdType } from '~/types'
import type { experimentSummaryLogicType } from './experimentSummaryLogicType'

export interface ExperimentSummaryLogicProps {
    experimentId: ExperimentIdType
}

export const experimentSummaryLogic = kea<experimentSummaryLogicType>([
    path((key) => ['scenes', 'experiments', 'components', 'AISummary', 'experimentSummaryLogic', key]),
    props({} as ExperimentSummaryLogicProps),
    connect((props: ExperimentSummaryLogicProps) => ({
        values: [
            experimentLogic(props),
            ['experiment', 'primaryMetricsResultsLoading', 'secondaryMetricsResultsLoading'],
        ],
    })),

    actions(() => ({
        generateSummary: true,
        resetSummary: true,
        updateSummary: (chunk: string) => ({ chunk }),
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
        isGenerating: [false, { generateSummary: () => true, resetSummary: () => false }],
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

            try {
                // Use api.stream() which handles CSRF automatically
                await api.stream(`/api/environments/@current/max_tools/experiment_results_summary/`, {
                    method: 'POST',
                    data: {
                        experiment_id: props.experimentId.toString(),
                    },
                    onMessage: (event) => {
                        try {
                            const data = JSON.parse(event.data)
                            if (data.content) {
                                actions.updateSummary(data.content)
                            }
                            if (data === '[DONE]') {
                                lemonToast.success('Summary generated successfully!')
                                return
                            }
                        } catch (e) {
                            console.error('Error generating summary:', e)
                            lemonToast.error('Failed to generate summary')
                        }
                    },
                    onError: (error) => {
                        console.error('Error generating summary:', error)
                        lemonToast.error('Failed to generate summary')
                    },
                })
            } catch (error) {
                console.error('Error generating summary:', error)
                lemonToast.error('Failed to generate summary')
                actions.resetSummary()
            }
        },
    })),
])
