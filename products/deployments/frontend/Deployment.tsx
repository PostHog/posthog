import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { CurrentDeploymentCard } from './components/CurrentDeploymentCard'
import { openRedeployDialog, openRollbackDialog } from './components/deploymentActions'
import { DeploymentLogsViewer } from './components/DeploymentLogsViewer'
import { deploymentLogic, DeploymentLogicProps } from './deploymentLogic'
import { deploymentProjectLogic } from './deploymentProjectLogic'

export const scene: SceneExport<DeploymentLogicProps> = {
    component: Deployment,
    logic: deploymentLogic,
    paramsToProps: ({ params: { projectId, deploymentId } }) => ({ projectId, id: deploymentId }),
}

export function Deployment({ projectId, id }: DeploymentLogicProps): JSX.Element {
    return (
        <BindLogic logic={deploymentProjectLogic} props={{ projectId }}>
            <BindLogic logic={deploymentLogic} props={{ projectId, id }}>
                <DeploymentInner projectId={projectId} id={id} />
            </BindLogic>
        </BindLogic>
    )
}

function DeploymentInner({ projectId, id }: DeploymentLogicProps): JSX.Element {
    const { deployment, deploymentMissing, deploymentLoading } = useValues(deploymentLogic({ projectId, id }))
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
            <DeploymentLogsViewer projectId={projectId} deploymentId={d.id} status={d.status} />
        </SceneContent>
    )
}

export default Deployment
