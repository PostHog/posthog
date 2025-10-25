import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { ExperimentsHog } from 'lib/components/hedgehogs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
// import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { ExperimentIdType } from '~/types'

import { experimentSummaryLogic } from './experimentSummaryLogic'

/**
 * This is a temporary wrapper component to handle the feature flag visibility
 * and to guarantee nothing leaks into the experiment page, like mounted logics.
 */
const AISummaryWrapper = ({ experimentId }: { experimentId: ExperimentIdType }): JSX.Element | null => {
    const isAISummaryEnabled = useFeatureFlag('EXPERIMENTS_AI_SUMMARY')

    if (!isAISummaryEnabled) {
        return null
    }

    return <AISummary experimentId={experimentId} />
}

const AISummary = ({ experimentId }: { experimentId: ExperimentIdType }): JSX.Element | null => {
    const { experiment } = useValues(experimentLogic({ experimentId }))

    const { isGenerating, summary } = useValues(experimentSummaryLogic({ experimentId }))
    const { generateSummary } = useActions(experimentSummaryLogic({ experimentId }))
    // const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    return (
        <AIConsentPopoverWrapper showArrow placement="bottom-start">
            <div className="relative">
                <MaxTool
                    identifier="experiment_results_summary"
                    context={{
                        experiment_data: experiment,
                        experiment_id: experimentId,
                    }}
                    callback={() => {}}
                    onMaxOpen={() => {}}
                >
                    <LemonCard hoverEffect={false}>
                        <div className="flex flex-row gap-2">
                            <ExperimentsHog className="w-16 h-16" />
                            <div className="flex flex-col gap-2 w-full">
                                <div className="flex items-center justify-between">
                                    <div className="flex gap-2">
                                        <IconSparkles />
                                        <span>Get AI-powered insights about your experiment results!</span>
                                    </div>

                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        loading={isGenerating}
                                        icon={<IconSparkles />}
                                        sideIcon={null}
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

export { AISummaryWrapper as AISummary }
