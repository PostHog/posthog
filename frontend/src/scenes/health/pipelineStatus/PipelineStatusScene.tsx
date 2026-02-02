import { useActions, useValues } from 'kea'

import { IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { SceneExport } from 'scenes/sceneTypes'

import { HealthIssueCard } from '~/layout/navigation-3000/sidepanel/panels/SidePanelHealth'
import { sidePanelHealthLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import { DataHealthIssue } from '~/layout/navigation-3000/sidepanel/panels/sidePanelHealthLogic'
import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { pipelineStatusSceneLogic } from './pipelineStatusSceneLogic'

export const scene: SceneExport = {
    component: PipelineStatusScene,
    logic: pipelineStatusSceneLogic,
}

export function PipelineStatusScene(): JSX.Element {
    const { issues, healthIssuesLoading, hasErrors, issueCount } = useValues(sidePanelHealthLogic)
    const { loadHealthIssues } = useActions(sidePanelHealthLogic)

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

            <div className="max-w-3xl">
                {healthIssuesLoading && issues.length === 0 ? (
                    <div className="space-y-3">
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
                        <LemonBanner type="warning" hideIcon={false} className="mb-4">
                            <p className="font-semibold">
                                {issueCount} issue{issueCount === 1 ? '' : 's'} need{issueCount === 1 ? 's' : ''}{' '}
                                attention
                            </p>
                            <p className="text-sm mt-1">
                                These data pipelines have failed or been disabled and may affect your data.
                            </p>
                        </LemonBanner>

                        <div className="space-y-3">
                            {issues.map((issue: DataHealthIssue) => (
                                <HealthIssueCard key={issue.id} issue={issue} />
                            ))}
                        </div>
                    </>
                )}
            </div>
        </SceneContent>
    )
}
