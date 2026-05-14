import { afterMount, connect, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { deploymentLogicType } from './deploymentLogicType'
import { deploymentsLogic } from './deploymentsLogic'
import { Deployment } from './fixtures'
import { deploymentProjectsDeploymentsRetrieve } from './generated/api'

export interface DeploymentLogicProps {
    id: string
}

export const deploymentLogic = kea<deploymentLogicType>([
    props({} as DeploymentLogicProps),
    key(({ id }) => id),
    path((key) => ['products', 'deployments', 'frontend', 'deploymentLogic', key]),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], deploymentsLogic, ['selectedProjectId', 'deploymentProjects']],
        actions: [deploymentsLogic, ['loadDeploymentProjects', 'redeployDeployment', 'rollbackDeployment']],
    })),
    loaders(({ values, props }) => ({
        deployment: [
            null as Deployment | null,
            {
                // Fetch the deployment by ID directly so the detail page works
                // even when the list view hasn't loaded it (different page,
                // different project, deep link).
                loadDeployment: async (): Promise<Deployment | null> => {
                    const teamId = values.currentTeamId
                    const projectId = values.selectedProjectId
                    if (!teamId || !projectId) {
                        return null
                    }
                    return deploymentProjectsDeploymentsRetrieve(String(teamId), projectId, props.id)
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
            (s) => [s.deployment],
            (d: Deployment | null): Breadcrumb[] => [
                { key: Scene.Deployments, name: 'Deployments', path: urls.deployments() },
                {
                    key: [Scene.Deployment, props.id],
                    name: d?.commit_message || d?.id || 'Deployment',
                },
            ],
        ],
    })),
    // Re-fetch the deployment whenever the project becomes known. On a deep
    // link the parent `deploymentsLogic` mounts alongside us but its project
    // list loads async, so `selectedProjectId` is `null` at `afterMount`. The
    // subscription fires once it lands.
    subscriptions(({ actions }) => ({
        selectedProjectId: (id: string | null) => {
            if (id) {
                actions.loadDeployment()
            }
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.deploymentProjects.length === 0) {
            actions.loadDeploymentProjects()
        }
        if (values.selectedProjectId) {
            actions.loadDeployment()
        }
    }),
])
