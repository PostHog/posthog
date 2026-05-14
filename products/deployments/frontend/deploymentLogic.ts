import { afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { deploymentLogicType } from './deploymentLogicType'
import { deploymentProjectLogic } from './deploymentProjectLogic'
import { deploymentsLogic } from './deploymentsLogic'
import { Deployment } from './fixtures'
import { deploymentProjectsDeploymentsRetrieve } from './generated/api'
import type { DeploymentProjectApi } from './generated/api.schemas'
import { getInitialStubDeployment, resolveStubDeploymentId, resolveStubProjectId } from './stubData'

export interface DeploymentLogicProps {
    projectId: string
    id: string
}

export const deploymentLogic = kea<deploymentLogicType>([
    props({} as DeploymentLogicProps),
    key(({ projectId, id }) => `${projectId}/${id}`),
    path((key) => ['products', 'deployments', 'frontend', 'deploymentLogic', key]),
    connect((props: DeploymentLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            deploymentProjectLogic({ projectId: props.projectId }),
            ['deploymentProject'],
            deploymentsLogic,
            ['isStubMode', 'stubDeploymentsByProject'],
        ],
        actions: [
            deploymentProjectLogic({ projectId: props.projectId }),
            ['redeployDeployment', 'rollbackDeployment'],
            deploymentsLogic,
            ['addStubDeployment', 'markStubDeploymentReady', 'loadDeploymentProjectsSuccess'],
        ],
    })),
    reducers({
        deploymentLoadAttempted: [
            false,
            {
                loadDeploymentSuccess: () => true,
                loadDeploymentFailure: () => true,
            },
        ],
    }),
    loaders(({ values, props }) => ({
        deployment: [
            null as Deployment | null,
            {
                loadDeployment: async (): Promise<Deployment | null> => {
                    const stubProjectId = resolveStubProjectId(props.projectId)
                    const stubDeploymentId = resolveStubDeploymentId(props.id)
                    const stubDeployment =
                        values.stubDeploymentsByProject[stubProjectId]?.find((d) => d.id === stubDeploymentId) ??
                        getInitialStubDeployment(props.projectId, props.id)
                    if (values.isStubMode || stubDeployment) {
                        return stubDeployment ?? null
                    }
                    const teamId = values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return deploymentProjectsDeploymentsRetrieve(String(teamId), props.projectId, props.id)
                },
            },
        ],
    })),
    selectors(({ props }) => ({
        deploymentMissing: [
            (s) => [s.deployment, s.deploymentLoading, s.deploymentLoadAttempted],
            (d: Deployment | null, loading: boolean, loadAttempted: boolean): boolean =>
                loadAttempted && !loading && !d,
        ],
        breadcrumbs: [
            (s) => [s.deployment, s.deploymentProject],
            (d: Deployment | null, project: DeploymentProjectApi | null): Breadcrumb[] => [
                { key: Scene.Deployments, name: 'Deployments', path: urls.deployments() },
                {
                    key: [Scene.DeploymentProject, props.projectId],
                    name: project?.name || 'Project',
                    path: urls.deploymentProject(project?.id ?? resolveStubProjectId(props.projectId)),
                },
                {
                    key: [Scene.Deployment, props.id],
                    name: d?.commit_message || d?.id || 'Deployment',
                },
            ],
        ],
    })),
    listeners(({ actions, props, values }) => ({
        addStubDeployment: ({ projectId, deployment }) => {
            if (
                projectId === resolveStubProjectId(props.projectId) &&
                deployment.id === resolveStubDeploymentId(props.id)
            ) {
                actions.loadDeployment()
            }
        },
        markStubDeploymentReady: ({ projectId, deployment }) => {
            if (
                projectId === resolveStubProjectId(props.projectId) &&
                deployment.id === resolveStubDeploymentId(props.id)
            ) {
                actions.loadDeployment()
            }
        },
        loadDeploymentProjectsSuccess: () => {
            if (values.isStubMode) {
                actions.loadDeployment()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDeployment()
    }),
])
