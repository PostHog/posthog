import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { FilterLogicalOperator, PropertyFilterType, PropertyOperator } from '~/types'

import { LogsViewer } from 'products/logs/frontend/components/LogsViewer/LogsViewer'

import { CurrentDeploymentCard } from './components/CurrentDeploymentCard'
import { deploymentLogic, DeploymentLogicProps } from './deploymentLogic'
import { deploymentsLogic } from './deploymentsLogic'
import { Deployment as DeploymentType } from './fixtures'

export const scene: SceneExport<DeploymentLogicProps> = {
    component: Deployment,
    logic: deploymentLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function Deployment({ id }: DeploymentLogicProps): JSX.Element {
    return (
        <BindLogic logic={deploymentLogic} props={{ id }}>
            <DeploymentInner id={id} />
        </BindLogic>
    )
}

function DeploymentInner({ id }: { id: string }): JSX.Element {
    const { deployment, deploymentMissing, deploymentLoading } = useValues(deploymentLogic({ id }))
    const { redeployDeployment, rollbackDeployment } = useActions(deploymentsLogic)

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

    const confirmRedeploy = (target: DeploymentType): void => {
        LemonDialog.open({
            title: 'Redeploy?',
            description: `This will start a new deployment based on ${target.commit_sha || target.id}. It will run through the build pipeline before becoming current.`,
            primaryButton: {
                children: 'Redeploy',
                type: 'primary',
                onClick: () => redeployDeployment(target.id),
            },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    const confirmRollback = (target: DeploymentType): void => {
        LemonDialog.open({
            title: 'Roll back to this deployment?',
            description: `This will immediately make ${target.commit_message || target.id} current.`,
            primaryButton: {
                children: 'Roll back',
                type: 'primary',
                status: 'danger',
                onClick: () => rollbackDeployment(target.id),
            },
            secondaryButton: { children: 'Cancel', type: 'secondary' },
        })
    }

    return (
        <SceneContent>
            <SceneTitleSection
                name={d.commit_message || d.commit_sha || d.id}
                description={d.branch ? `Branch: ${d.branch}` : undefined}
                resourceType={{ type: 'deployments' }}
                actions={
                    <>
                        <LemonButton type="secondary" onClick={() => confirmRedeploy(d)}>
                            Redeploy
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            onClick={() => confirmRollback(d)}
                            disabledReason={d.is_current ? 'Already current' : undefined}
                        >
                            Rollback
                        </LemonButton>
                    </>
                }
            />
            <CurrentDeploymentCard deployment={d} />
            <div className="flex flex-col gap-2">
                <h3 className="text-lg font-semibold">Logs</h3>
                <p className="text-secondary text-sm">
                    Filtered to this deployment via the <code>deployment_id</code> attribute. Once ingestion stamps that
                    attribute, real entries will show here.
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
            </div>
        </SceneContent>
    )
}

export default Deployment
