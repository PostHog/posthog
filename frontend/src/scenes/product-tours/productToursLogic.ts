import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { Breadcrumb, ProductTour, ProgressStatus } from '~/types'

import type { productToursLogicType } from './productToursLogicType'

export enum ProductToursTabs {
    Active = 'active',
    Archived = 'archived',
}

export function getProductTourStatus(tour: Pick<ProductTour, 'start_date' | 'end_date'>): ProgressStatus {
    if (!tour.start_date) {
        return ProgressStatus.Draft
    } else if (!tour.end_date) {
        return ProgressStatus.Running
    }
    return ProgressStatus.Complete
}

export function isProductTourRunning(tour: Pick<ProductTour, 'start_date' | 'end_date'>): boolean {
    return getProductTourStatus(tour) === ProgressStatus.Running
}

export interface ProductToursFilters {
    archived: boolean
}

export const productToursLogic = kea<productToursLogicType>([
    path(['scenes', 'product-tours', 'productToursLogic']),
    connect(() => ({})),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setFilters: (filters: Partial<ProductToursFilters>) => ({ filters }),
        setTab: (tab: ProductToursTabs) => ({ tab }),
    }),
    loaders(({ values }) => ({
        productTours: {
            __default: [] as ProductTour[],
            loadProductTours: async () => {
                const response: PaginatedResponse<ProductTour> = await api.productTours.list()
                return response.results
            },
            deleteProductTour: async (id: string) => {
                await api.productTours.delete(id)
                deleteFromTree('product_tour', id)
                lemonToast.success('Product tour deleted')
                return values.productTours.filter((t: ProductTour) => t.id !== id)
            },
            updateProductTour: async ({ id, updatePayload }: { id: string; updatePayload: Partial<ProductTour> }) => {
                const updatedTour = await api.productTours.update(id, updatePayload)
                lemonToast.success('Product tour updated')
                return values.productTours.map((t: ProductTour) => (t.id === id ? updatedTour : t))
            },
        },
    })),
    reducers({
        tab: [
            ProductToursTabs.Active as ProductToursTabs,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        filters: [
            { archived: false } as ProductToursFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    listeners(({ actions }) => ({
        setTab: ({ tab }) => {
            actions.setFilters({ archived: tab === ProductToursTabs.Archived })
        },
        deleteProductTourSuccess: () => {
            router.actions.push(urls.productTours())
        },
    })),
    selectors({
        filteredProductTours: [
            (s) => [s.productTours, s.searchTerm, s.filters],
            (productTours: ProductTour[], searchTerm: string, filters: ProductToursFilters) => {
                let filtered = productTours

                if (searchTerm) {
                    const fuse = new Fuse(filtered, {
                        keys: ['name', 'description'],
                        ignoreLocation: true,
                        threshold: 0.3,
                    })
                    filtered = fuse.search(searchTerm).map((result) => result.item)
                }

                if (filters.archived) {
                    filtered = filtered.filter((tour: ProductTour) => tour.archived)
                } else {
                    filtered = filtered.filter((tour: ProductTour) => !tour.archived)
                }

                return filtered
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.ProductTours,
                    name: sceneConfigurations[Scene.ProductTours].name || 'Product tours',
                    path: urls.productTours(),
                },
            ],
        ],
    }),
    actionToUrl(({ values }) => ({
        setTab: () => {
            return [router.values.location.pathname, { ...router.values.searchParams, tab: values.tab }]
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.productTours()]: (_, { tab }) => {
            if (tab) {
                actions.setTab(tab as ProductToursTabs)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadProductTours()
    }),
])
