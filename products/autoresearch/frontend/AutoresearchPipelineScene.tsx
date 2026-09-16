import { useActions, useValues } from 'kea'

import { LemonTab, LemonTabs, Spinner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    AutoresearchPipelineLogicProps,
    AutoresearchPipelineTab,
    autoresearchPipelineLogic,
} from './autoresearchPipelineLogic'
import { OnlinePerformanceTab } from './pipeline/OnlinePerformanceTab'
import { OverviewTab } from './pipeline/OverviewTab'
import { PipelineActions } from './pipeline/PipelineActions'
import { PredictionsTab } from './pipeline/PredictionsTab'
import { ScoreNowButton } from './pipeline/ScoreNowButton'
import { SuggestionsTab } from './pipeline/SuggestionsTab'
import { TrainingTab } from './pipeline/TrainingTab'

export const scene: SceneExport = {
    component: AutoresearchPipelineScene,
    logic: autoresearchPipelineLogic,
    paramsToProps: ({ params: { id } }): AutoresearchPipelineLogicProps => ({ id }),
}

export function AutoresearchPipelineScene(): JSX.Element {
    const { pipeline, pipelineLoading, activeTab } = useValues(autoresearchPipelineLogic)
    const { setActiveTab } = useActions(autoresearchPipelineLogic)

    const tabs: LemonTab<AutoresearchPipelineTab>[] = [
        { key: 'overview', label: 'Overview', content: <OverviewTab /> },
        { key: 'training', label: 'Training', content: <TrainingTab /> },
        { key: 'predictions', label: 'Predictions', content: <PredictionsTab /> },
        { key: 'online_performance', label: 'Online performance', content: <OnlinePerformanceTab /> },
        { key: 'suggestions', label: 'Suggestions', content: <SuggestionsTab /> },
    ]

    const heading = pipeline?.name ?? (pipelineLoading ? '' : 'Model')
    const subheading = pipeline ? `Predict ${pipeline.target_event} within ${pipeline.horizon_days ?? '?'}d` : undefined

    return (
        <SceneContent>
            <SceneTitleSection
                name={heading}
                description={subheading}
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
            ) : (
                <LemonTabs
                    activeKey={activeTab}
                    onChange={(key) => setActiveTab(key as AutoresearchPipelineTab)}
                    tabs={tabs}
                    sceneInset
                />
            )}
        </SceneContent>
    )
}
