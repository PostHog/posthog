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
                // Use the standardized /max_tools endpoint with the experiment_results_summary tool
                const response = await api.create(`/api/environments/@current/max_tools/experiment_results_summary/`, {
                    experiment_id: props.experimentId.toString(),
                })

                // Parse the response to extract the summary content
                if (response && Array.isArray(response)) {
                    let summaryContent = ''
                    for (const message of response) {
                        if (message.type === 'message' && message.data?.content) {
                            summaryContent += message.data.content + '\n'
                        } else if (message.type === 'ai' && message.content) {
                            summaryContent += message.content + '\n'
                        }
                    }

                    if (summaryContent.trim()) {
                        actions.updateSummary(summaryContent.trim())
                        lemonToast.success('Summary generated successfully!')
                    } else {
                        lemonToast.error('No summary content received')
                        actions.resetSummary()
                    }
                } else {
                    lemonToast.error('Unexpected response format')
                    actions.resetSummary()
                }
            } catch (error) {
                console.error('Error generating summary:', error)
                lemonToast.error('Failed to generate summary')
                actions.resetSummary()
            }
        },
    })),
])
