import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useState } from 'react'
import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { MaxTool } from 'scenes/max/MaxTool'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'
import { ExperimentIdType } from '~/types'

export const AISummary = ({ experimentId }: { experimentId: ExperimentIdType }): JSX.Element | null => {
    const isAISummaryEnabled = useFeatureFlag('EXPERIMENTS_AI_SUMMARY')
    const { experiment, legacyMetricResults } = useValues(experimentLogic({ experimentId }))
    // const { dataProcessingAccepted } = useValues(maxGlobalLogic)

    const [isGenerating, setIsGenerating] = useState(false)

    if (!isAISummaryEnabled) {
        return null
    }

    const experimentData = {
        name: experiment?.name,
        description: experiment?.description,
        results: legacyMetricResults?.[0] || {},
        experiment_id: experimentId,
    }

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
                    <LemonBanner type="info">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <IconSparkles />
                                <span>Get AI-powered insights about your experiment results!</span>
                            </div>

                            <LemonButton size="small" loading={isGenerating} icon={<IconSparkles />}>
                                {isGenerating ? 'Generating...' : 'Generate Results Summary'}
                            </LemonButton>
                        </div>
                    </LemonBanner>
                </MaxTool>
            </div>
        </AIConsentPopoverWrapper>
    )
}
