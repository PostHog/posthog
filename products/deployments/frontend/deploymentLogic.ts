import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { deploymentLogicType } from './deploymentLogicType'
import { deploymentProjectLogic } from './deploymentProjectLogic'
import { Deployment } from './fixtures'
import { deploymentProjectsDeploymentsRetrieve } from './generated/api'
import type { DeploymentProjectApi } from './generated/api.schemas'

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
        ],
        actions: [deploymentProjectLogic({ projectId: props.projectId }), ['redeployDeployment', 'rollbackDeployment']],
    })),
    loaders(({ values, props }) => ({
        deployment: [
            null as Deployment | null,
            {
                loadDeployment: async (): Promise<Deployment | null> => {
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
            (s) => [s.deployment, s.deploymentLoading],
            (d: Deployment | null, loading: boolean): boolean => !loading && !d,
        ],
        breadcrumbs: [
            (s) => [s.deployment, s.deploymentProject],
            (d: Deployment | null, project: DeploymentProjectApi | null): Breadcrumb[] => [
                { key: Scene.Deployments, name: 'Deployments', path: urls.deployments() },
                {
                    key: [Scene.DeploymentProject, props.projectId],
                    name: project?.name || 'Project',
                    path: urls.deploymentProject(props.projectId),
                },
                {
                    key: [Scene.Deployment, props.id],
                    name: d?.commit_message || d?.id || 'Deployment',
                },
            ],
        ],
    })),
    afterMount(({ actions }) => {
        actions.loadDeployment()
    }),
])
