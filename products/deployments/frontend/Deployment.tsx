import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'

import { CurrentDeploymentCard } from './components/CurrentDeploymentCard'
import { openRedeployDialog, openRollbackDialog } from './components/deploymentActions'
import { StubBuildLogs } from './components/StubBuildLogs'
import { deploymentLogic, DeploymentLogicProps } from './deploymentLogic'
import { deploymentProjectLogic } from './deploymentProjectLogic'
import { deploymentsLogic } from './deploymentsLogic'

export const scene: SceneExport<DeploymentLogicProps> = {
    component: Deployment,
    logic: deploymentLogic,
    paramsToProps: ({ params: { projectId, deploymentId } }) => ({
        projectId,
        id: deploymentId,
    }),
}

interface DeploymentSceneProps {
    projectId: string
    id?: string
    deploymentId?: string
}

export function Deployment({ projectId, id, deploymentId }: DeploymentSceneProps): JSX.Element {
    const resolvedDeploymentId = id ?? deploymentId

    if (!resolvedDeploymentId) {
        return (
            <SceneContent>
                <NotFound object="deployment" />
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={deploymentProjectLogic} props={{ projectId }}>
            <BindLogic logic={deploymentLogic} props={{ projectId, id: resolvedDeploymentId }}>
                <DeploymentInner projectId={projectId} id={resolvedDeploymentId} />
            </BindLogic>
        </BindLogic>
    )
}

function DeploymentInner({ projectId, id }: DeploymentLogicProps): JSX.Element {
    const { deployment, deploymentMissing, deploymentLoading } = useValues(deploymentLogic({ projectId, id }))
    const { deploymentProject } = useValues(deploymentProjectLogic({ projectId }))
    const { isStubMode } = useValues(deploymentsLogic)
    const { redeployDeployment, rollbackDeployment } = useActions(deploymentProjectLogic({ projectId }))

    if (deploymentMissing) {
        return (
            <SceneContent>
                <NotFound object="deployment" />
            </SceneContent>
        )
    }

    if (deploymentLoading || !deployment) {
        return (
            <SceneContent>
                <SceneTitleSection name="Deployment" description="Loading…" resourceType={{ type: 'deployments' }} />
            </SceneContent>
        )
    }

    const d = deployment

    return (
        <SceneContent>
            <SceneTitleSection
                name={d.commit_message || d.commit_sha || d.id}
                description={d.branch ? `Branch: ${d.branch}` : undefined}
                resourceType={{ type: 'deployments' }}
                actions={
                    <>
                        <LemonButton type="secondary" onClick={() => openRedeployDialog(d, redeployDeployment)}>
                            Redeploy
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => openRollbackDialog(d, rollbackDeployment)}
                            disabledReason={d.is_current ? 'Already current' : undefined}
                        >
                            Rollback
                        </LemonButton>
                    </>
                }
            />
            <CurrentDeploymentCard deployment={d} />
            <div className="flex flex-col gap-2">
                {isStubMode ? (
                    <StubBuildLogs deployment={d} project={deploymentProject} />
                ) : (
                    <>
                        <h3 className="text-lg font-semibold">Logs</h3>
                        <p className="text-secondary text-sm">
                            Filtered to this deployment via the <code>deployment_id</code> attribute. Once ingestion
                            stamps that attribute, real entries will show here.
                        </p>
                        <LogsViewer
                            id={`deployment-${id}`}
                            initialFilters={{
                                filterGroup: {
                                    type: FilterLogicalOperator.And,
                                    values: [
                                        {
                                            type: FilterLogicalOperator.And,
                                            values: [
                                                {
                                                    key: 'deployment_id',
                                                    type: PropertyFilterType.LogAttribute,
                                                    operator: PropertyOperator.Exact,
                                                    value: id,
                                                } as any,
                                            ],
                                        },
                                    ],
                                },
                            }}
                            showFullScreenButton={false}
                            showSavedViewsButton={false}
                        />
                    </>
                )}
            </div>
        </SceneContent>
    )
}

export default Deployment
