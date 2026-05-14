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
                    // The DRF list endpoint is paginated; walk every page so the
                    // table never silently drops rows on larger catalogs.
                    const projectId = String(values.currentProjectId)
                    const limit = 200
                    const all: CatalogNodeDTOApi[] = []
                    for (let offset = 0; ; offset += limit) {
                        const page = await catalogNodesList(projectId, { limit, offset })
                        all.push(...page.results)
                        if (!page.next || page.results.length < limit) {
                            break
                        }
                    }
                    return all
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'catalog', name: 'Catalog' }]],
    }),

    urlToAction(({ actions }) => ({
        '/catalog/list': () => {
            actions.loadNodes()
        },
    })),
])
