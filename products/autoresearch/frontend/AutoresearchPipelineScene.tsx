import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTab, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    AutoresearchPipelineLogicProps,
    AutoresearchPipelineTab,
    autoresearchPipelineLogic,
} from './autoresearchPipelineLogic'
import { AgentResearchTab } from './pipeline/AgentResearchTab'
import { LifecycleStrip } from './pipeline/LifecycleStrip'
import { OnlinePerformanceTab } from './pipeline/OnlinePerformanceTab'
import { PipelineActions } from './pipeline/PipelineActions'
import { PipelineSummary } from './pipeline/PipelineSummary'
import { PredictionsTab } from './pipeline/PredictionsTab'
import { ScoreNowButton } from './pipeline/ScoreNowButton'
import { SetupTab } from './pipeline/SetupTab'
import { pipelineQuestion } from './pipelineQuestion'

export const scene: SceneExport = {
    component: AutoresearchPipelineScene,
    logic: autoresearchPipelineLogic,
    paramsToProps: ({ params: { id } }): AutoresearchPipelineLogicProps => ({ id }),
}

export function AutoresearchPipelineScene(): JSX.Element {
    const { pipeline, pipelineLoading, pipelineError, activeTab, lifecycleSteps } = useValues(autoresearchPipelineLogic)
    const { setActiveTab, loadDetail } = useActions(autoresearchPipelineLogic)
    const isEnabled = useFeatureFlag('AUTORESEARCH')

    const tabs: LemonTab<AutoresearchPipelineTab>[] = [
        { key: 'predictions', label: 'Predictions', content: <PredictionsTab /> },
        { key: 'accuracy', label: 'Accuracy', content: <OnlinePerformanceTab /> },
        { key: 'agent_research', label: 'Agent research', content: <AgentResearchTab /> },
        { key: 'setup', label: 'Setup', content: <SetupTab /> },
    ]

    const heading = pipeline ? pipelineQuestion(pipeline) : pipelineLoading ? '' : 'Model'

    if (!isEnabled) {
        return <NotFound object="Autoresearch" caption="This feature is not enabled for your project." />
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={heading}
                description={pipeline?.name ?? null}
                resourceType={{ type: 'experiment' }}
                actions={
                    <>
                        <ScoreNowButton />
                        <PipelineActions />
                    </>
                }
            />

            {pipelineLoading && !pipeline ? (
                <Spinner />
            ) : pipelineError && !pipeline ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Retry', onClick: () => loadDetail(), 'data-attr': 'autoresearch-model-retry' }}
                >
                    Couldn't load this model. It may have been deleted. Try again, or go back to the model list.
                </LemonBanner>
            ) : (
                <>
                    <PipelineSummary />
                    {lifecycleSteps && <LifecycleStrip steps={lifecycleSteps} />}
                    <LemonTabs
                        activeKey={activeTab}
                        onChange={(key) => setActiveTab(key as AutoresearchPipelineTab)}
                        tabs={tabs}
                        sceneInset
                    />
                </>
            )}
        </SceneContent>
    )
}
