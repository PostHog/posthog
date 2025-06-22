import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { ExperimentsHog } from 'lib/components/hedgehogs'
import { dayjs } from 'lib/dayjs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCard } from 'lib/lemon-ui/LemonCard'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
// import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { Experiment, ExperimentIdType } from '~/types'
import { experimentSummaryLogic } from './experimentSummaryLogic'

const getExperimentDataForMaxTool = (
    experiment: Experiment,
    primaryMetricsResults: any[],
    secondaryMetricsResults: any[]
) => {
    const daysRunning = dayjs(experiment.start_date).diff(dayjs(), 'days')
    const daysRemaining = dayjs(experiment.end_date).diff(dayjs(), 'days')

    return {
        experiment_id: experiment.id,
        name: experiment.name,
        description: experiment.description,
        daysRunning: daysRunning || 0,
        daysRemaining: daysRemaining || 0,
        primaryMetricsResults,
        secondaryMetricsResults,
    }
}

export const AISummary = ({ experimentId }: { experimentId: ExperimentIdType }): JSX.Element | null => {
    const isAISummaryEnabled = useFeatureFlag('EXPERIMENTS_AI_SUMMARY')
    const { experiment, primaryMetricsResults, secondaryMetricsResults } = useValues(experimentLogic({ experimentId }))

    const { isGenerating, summary } = useValues(experimentSummaryLogic({ experimentId }))
    const { generateSummary, resetSummary } = useActions(experimentSummaryLogic({ experimentId }))
    // const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    if (!isAISummaryEnabled) {
        return null
    }

    const experimentData = getExperimentDataForMaxTool(experiment, primaryMetricsResults, secondaryMetricsResults)

    return (
        <AIConsentPopoverWrapper showArrow placement="bottom-start">
            <div className="relative">
                <MaxTool
                    name="experiment_results_summary"
                    displayName="Generate Experiment Results Summary"
                    context={{
                        experiment_data: experimentData,
                        experiment_id: experimentId,
                    }}
                    callback={() => {
                        console.log('callback')
                    }}
                    onMaxOpen={() => {
                        console.log('onMaxOpen')
                    }}
                >
                    <LemonCard hoverEffect={false}>
                        <div className="flex flex-row gap-2">
                            <ExperimentsHog className="w-16 h-16" />
                            <div className="flex flex-col gap-2">
                                <div className="flex items-center justify-between">
                                    <div className="flex gap-2">
                                        <IconSparkles />
                                        <span>Get AI-powered insights about your experiment results!</span>
                                    </div>

                                    <LemonButton
                                        size="small"
                                        loading={isGenerating}
                                        icon={<IconSparkles />}
                                        onClick={generateSummary}
                                    >
                                        {isGenerating ? 'Generating...' : 'Generate Results Summary'}
                                    </LemonButton>
                                </div>
                                {summary ? (
                                    <div className="whitespace-pre-wrap">{summary}</div>
                                ) : (
                                    <div className="whitespace-pre-wrap">No summary generated yet</div>
                                )}
                            </div>
                        </div>
                    </LemonCard>
                </MaxTool>
            </div>
        </AIConsentPopoverWrapper>
    )
}
