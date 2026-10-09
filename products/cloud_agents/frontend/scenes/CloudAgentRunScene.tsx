import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { LoadErrorBanner } from '../components/LoadErrorBanner'
import { RunCostCard } from '../components/RunCostCard'
import { RunFollowupComposer } from '../components/RunFollowupComposer'
import { RunHeaderActions } from '../components/RunHeaderActions'
import { RunSessionsCard } from '../components/RunSessionsCard'
import { RunSummaryCard } from '../components/RunSummaryCard'
import { RunTimeline } from '../components/RunTimeline'
import { CloudAgentRunLogicProps, cloudAgentRunLogic } from '../logics/cloudAgentRunLogic'

export const scene: SceneExport<CloudAgentRunLogicProps> = {
    component: CloudAgentRunScene,
    logic: cloudAgentRunLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
    productKey: ProductKey.CLOUD_AGENTS,
}

export function CloudAgentRunScene({ id }: CloudAgentRunLogicProps): JSX.Element {
    const enabled = useFeatureFlag('CLOUD_AGENTS')
    const logic = cloudAgentRunLogic({ id })
    const { run, runLoading, runLoadError, cancelError } = useValues(logic)
    const { loadRun } = useActions(logic)

    if (!enabled || runLoadError === 'not_found') {
        return <NotFound object="run" caption="Check the link, or open the list of runs to find it." />
    }

    return (
        <BindLogic logic={cloudAgentRunLogic} props={{ id }}>
            <SceneContent>
                <SceneTitleSection
                    name={run ? run.prompt.split('\n')[0].slice(0, 80) : 'Run'}
                    resourceType={{ type: 'cloud_agent' }}
                    forceBackTo={{ key: 'cloud-agents', name: 'Cloud agents', path: urls.cloudAgents() }}
                    actions={<RunHeaderActions />}
                />
                {run === null && runLoadError === 'failed' ? (
                    <LoadErrorBanner what="this run" onRetry={loadRun} retrying={runLoading} />
                ) : run === null ? (
                    <div className="flex flex-col gap-3" data-attr="cloud-agents-run-loading">
                        <LemonSkeleton className="h-32" />
                        <LemonSkeleton className="h-64" />
                    </div>
                ) : (
                    <>
                        {cancelError && <LemonBanner type="error">{cancelError}</LemonBanner>}
                        {/* The cost column comes second in the source, so a narrow scene shows the cost before the timeline. */}
                        <div className="grid grid-cols-1 items-start gap-4 @min-[56rem]/main-content:grid-cols-3">
                            <div className="min-w-0 @min-[56rem]/main-content:col-span-2">
                                <RunSummaryCard run={run} />
                            </div>
                            <div className="flex min-w-0 flex-col gap-4 @min-[56rem]/main-content:row-span-2">
                                <RunCostCard run={run} />
                                <RunSessionsCard sessions={run.agent_sessions} />
                            </div>
                            <div className="flex min-w-0 flex-col gap-4 @min-[56rem]/main-content:col-span-2">
                                <RunTimeline />
                                <RunFollowupComposer />
                            </div>
                        </div>
                    </>
                )}
            </SceneContent>
        </BindLogic>
    )
}
