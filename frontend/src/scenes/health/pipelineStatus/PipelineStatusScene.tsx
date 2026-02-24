import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'

import { HealthIssueCard } from '~/layout/navigation-3000/sidepanel/panels/SidePanelHealth'
import { sidePanelHealthLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import type { DataHealthIssue } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { PipelineStatusSummary } from './PipelineStatusSummary'
import { PipelineStatusToolbar } from './PipelineStatusToolbar'
import { pipelineStatusSceneLogic } from './pipelineStatusSceneLogic'

export const scene: SceneExport = {
    component: PipelineStatusScene,
    logic: pipelineStatusSceneLogic,
}

export function PipelineStatusScene(): JSX.Element {
    const { issues, healthIssuesLoading, hasErrors, issueCount } = useValues(sidePanelHealthLogic)
    const { loadHealthIssues } = useActions(sidePanelHealthLogic)
    const { filteredIssues, filteredIssueCount, isIssueDismissed } = useValues(pipelineStatusSceneLogic)
    const { dismissIssue, undismissIssue } = useActions(pipelineStatusSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Pipeline status"
                description="Monitor the status of your data pipelines."
                resourceType={{
                    to: undefined,
                    type: 'pipeline_status',
                }}
                actions={
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconRefresh className="size-4" />}
                        disabledReason={healthIssuesLoading ? 'Refreshing...' : undefined}
                        onClick={() => loadHealthIssues()}
                    >
                        {healthIssuesLoading ? 'Refreshing...' : 'Refresh'}
                    </LemonButton>
                }
            />

            <div className="max-w-3xl space-y-4">
                {healthIssuesLoading && issues.length === 0 ? (
                    <div className="space-y-3">
                        <LemonSkeleton className="h-8" />
                        <LemonSkeleton className="h-20" />
                        <LemonSkeleton className="h-20" />
                    </div>
                ) : hasErrors ? (
                    <div className="text-center text-muted p-4">
                        Error loading health information. Please try again later.
                    </div>
                ) : issueCount === 0 ? (
                    <LemonBanner type="success" hideIcon={false}>
                        <p className="font-semibold">All data pipelines healthy</p>
                        <p className="text-sm mt-1">
                            Your sources, syncs, destinations, and transformations are running without issues.
                        </p>
                    </LemonBanner>
                ) : (
                    <>
                        <PipelineStatusSummary />
                        <PipelineStatusToolbar />

                        {filteredIssueCount === 0 ? (
                            <div className="text-center text-muted p-8">No issues match your filters.</div>
                        ) : (
                            <div className="space-y-3">
                                {filteredIssues.map((issue: DataHealthIssue) => (
                                    <HealthIssueCard
                                        key={issue.id}
                                        issue={issue}
                                        isDismissed={isIssueDismissed(issue.id)}
                                        onDismiss={() => dismissIssue(issue.id)}
                                        onUndismiss={() => undismissIssue(issue.id)}
                                    />
                                ))}
                            </div>
                        )}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
