import { connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import { catalogNodesList } from 'products/catalog/frontend/generated/api'
import type { CatalogNodeDTOApi } from 'products/catalog/frontend/generated/api.schemas'

import type { catalogListSceneLogicType } from './catalogListSceneLogicType'

export const catalogListSceneLogic = kea<catalogListSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogListSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    loaders(({ values }) => ({
        nodes: [
            [] as CatalogNodeDTOApi[],
            {
                loadNodes: async () => {
                    const response = await catalogNodesList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'catalog', name: 'Catalog' }]],
    }),

    urlToAction(({ actions }) => ({
        '/catalog': () => {
            actions.loadNodes()
        },
    })),
])
