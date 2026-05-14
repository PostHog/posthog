import { actions, afterMount, kea, key, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import type { deploymentsLogicType } from './deploymentsLogicType'
import type { DeploymentApi } from './generated/api.schemas'

export interface DeploymentsFilters {
    status: string | null
    author: string | null
    search: string
}

export const DEFAULT_DEPLOYMENT_FILTERS: DeploymentsFilters = {
    status: null,
    author: null,
    search: '',
}

export interface DeploymentsLogicProps {
    tabId: string
}

export const deploymentsLogic = kea<deploymentsLogicType>([
    path(['products', 'deployments', 'frontend', 'deploymentsLogic']),
    props({} as DeploymentsLogicProps),
    key((props) => props.tabId),
    actions({
        // TODO(deployments-v1): wire setFilters once <DeploymentsFilters/> exists.
        setFilters: (filters: Partial<DeploymentsFilters>) => ({ filters }),
    }),
    loaders(() => ({
        deployments: [
            [] as DeploymentApi[],
            {
                loadDeployments: async () => {
                    // Deployments are now nested under DeploymentProject; the list scene
                    // owned by the Frontend stream will pick a project and call
                    // `deploymentProjectsDeploymentsList(projectId, deploymentProjectId)`.
                    return []
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_DEPLOYMENT_FILTERS,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDeployments()
    }),
    // TODO(deployments-v1): switch to tabAwareUrlToAction once filters live in the URL.
    urlToAction(() => ({
        [urls.deployments()]: () => {
            // placeholder — nothing to read from the URL yet.
        },
    })),
    actionToUrl(() => ({
        // TODO(deployments-v1): push filter state into the URL.
    })),
])
