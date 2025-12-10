import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { hogql } from '~/queries/utils'
import { Breadcrumb, FeatureFlagFilters, ProductTour, ProductTourContent } from '~/types'

import type { productTourLogicType } from './productTourLogicType'
import { productToursLogic } from './productToursLogic'

export interface ProductTourLogicProps {
    id: string
}

export interface ProductTourStats {
    shown: number
    completed: number
    dismissed: number
    stepStats: Array<{
        stepOrder: number
        shown: number
        completed: number
    }>
}

export interface ProductTourForm {
    name: string
    description: string
    content: ProductTourContent
    targeting_flag_filters: FeatureFlagFilters | null
}

const NEW_PRODUCT_TOUR: ProductTourForm = {
    name: '',
    description: '',
    content: { steps: [] },
    targeting_flag_filters: null,
}

export const productTourLogic = kea<productTourLogicType>([
    path(['scenes', 'product-tours', 'productTourLogic']),
    props({} as ProductTourLogicProps),
    key((props) => props.id),
    connect(() => ({
        actions: [productToursLogic, ['loadProductTours']],
    })),
    actions({
        editingProductTour: (editing: boolean) => ({ editing }),
        setProductTourValue: (key: keyof ProductTourForm, value: any) => ({ key, value }),
        setFlagPropertyErrors: (errors: any) => ({ errors }),
        launchProductTour: true,
        stopProductTour: true,
        resumeProductTour: true,
    }),
    loaders(({ props, values }) => ({
        productTour: {
            __default: null as ProductTour | null,
            loadProductTour: async () => {
                if (props.id === 'new') {
                    return null
                }
                return await api.productTours.get(props.id)
            },
        },
        tourStats: {
            __default: null as ProductTourStats | null,
            loadTourStats: async () => {
                if (props.id === 'new' || !values.productTour) {
                    return null
                }

                // Query for overall tour stats
                const tourStatsQuery = hogql`
                    SELECT
                        event,
                        count() as count
                    FROM events
                    WHERE event IN ('product tour shown', 'product tour completed', 'product tour dismissed')
                        AND properties.$product_tour_id = ${props.id}
                    GROUP BY event
                `

                // Query for step-level stats
                const stepStatsQuery = hogql`
                    SELECT
                        JSONExtractInt(properties, '$product_tour_step_order') as step_order,
                        event,
                        count() as count
                    FROM events
                    WHERE event IN ('product tour step shown', 'product tour step completed')
                        AND properties.$product_tour_id = ${props.id}
                    GROUP BY step_order, event
                    ORDER BY step_order
                `

                try {
                    const [tourStatsResponse, stepStatsResponse] = await Promise.all([
                        api.query({ kind: 'HogQLQuery', query: tourStatsQuery }),
                        api.query({ kind: 'HogQLQuery', query: stepStatsQuery }),
                    ])

                    const tourResults = (tourStatsResponse as any)?.results || []
                    const stepResults = (stepStatsResponse as any)?.results || []

                    // Process tour stats
                    let shown = 0
                    let completed = 0
                    let dismissed = 0

                    for (const [event, count] of tourResults) {
                        if (event === 'product tour shown') {
                            shown = count
                        } else if (event === 'product tour completed') {
                            completed = count
                        } else if (event === 'product tour dismissed') {
                            dismissed = count
                        }
                    }

                    // Process step stats
                    const stepStatsMap = new Map<number, { shown: number; completed: number }>()
                    for (const [stepOrder, event, count] of stepResults) {
                        if (!stepStatsMap.has(stepOrder)) {
                            stepStatsMap.set(stepOrder, { shown: 0, completed: 0 })
                        }
                        const step = stepStatsMap.get(stepOrder)!
                        if (event === 'product tour step shown') {
                            step.shown = count
                        } else if (event === 'product tour step completed') {
                            step.completed = count
                        }
                    }

                    const stepStats = Array.from(stepStatsMap.entries())
                        .sort(([a], [b]) => a - b)
                        .map(([stepOrder, stats]) => ({
                            stepOrder,
                            ...stats,
                        }))

                    return { shown, completed, dismissed, stepStats }
                } catch (error) {
                    console.error('Failed to load tour stats:', error)
                    return null
                }
            },
        },
    })),
    forms(({ actions, props }) => ({
        productTourForm: {
            defaults: NEW_PRODUCT_TOUR as ProductTourForm,
            errors: ({ name }: ProductTourForm) => ({
                name: !name ? 'Name is required' : undefined,
            }),
            submit: async (formValues: ProductTourForm) => {
                const payload = {
                    name: formValues.name,
                    description: formValues.description,
                    content: formValues.content,
                    targeting_flag_filters: formValues.targeting_flag_filters,
                }

                if (props.id && props.id !== 'new') {
                    await api.productTours.update(props.id, payload)
                    lemonToast.success('Product tour updated')
                    actions.editingProductTour(false)
                    actions.loadProductTour()
                    actions.loadProductTours()
                }
            },
        },
    })),
    reducers({
        productTourMissing: [
            false,
            {
                loadProductTourSuccess: (_, { productTour }) => !productTour,
                loadProductTourFailure: () => true,
            },
        ],
        isEditingProductTour: [
            false,
            {
                editingProductTour: (_, { editing }) => editing,
            },
        ],
        flagPropertyErrors: [
            null as any,
            {
                setFlagPropertyErrors: (_, { errors }) => errors,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        launchProductTour: async () => {
            if (values.productTour) {
                await api.productTours.update(values.productTour.id, {
                    start_date: new Date().toISOString(),
                })
                lemonToast.success('Product tour launched')
                actions.loadProductTour()
                actions.loadProductTours()
            }
        },
        stopProductTour: async () => {
            if (values.productTour) {
                await api.productTours.update(values.productTour.id, {
                    end_date: new Date().toISOString(),
                })
                lemonToast.success('Product tour stopped')
                actions.loadProductTour()
                actions.loadProductTours()
            }
        },
        resumeProductTour: async () => {
            if (values.productTour) {
                await api.productTours.update(values.productTour.id, {
                    end_date: null,
                })
                lemonToast.success('Product tour resumed')
                actions.loadProductTour()
                actions.loadProductTours()
            }
        },
        loadProductTourSuccess: ({ productTour }) => {
            actions.loadTourStats()
            // Populate form with loaded data
            if (productTour) {
                actions.setProductTourFormValues({
                    name: productTour.name,
                    description: productTour.description,
                    content: productTour.content,
                    targeting_flag_filters: productTour.targeting_flag_filters,
                })
            }
        },
        editingProductTour: ({ editing }) => {
            if (editing && values.productTour) {
                // Reset form to current tour values when entering edit mode
                actions.setProductTourFormValues({
                    name: values.productTour.name,
                    description: values.productTour.description,
                    content: values.productTour.content,
                    targeting_flag_filters: values.productTour.targeting_flag_filters,
                })
            }
        },
    })),
    selectors({
        breadcrumbs: [
            (s) => [s.productTour],
            (productTour: ProductTour | null): Breadcrumb[] => [
                {
                    key: Scene.ProductTours,
                    name: sceneConfigurations[Scene.ProductTours].name || 'Product tours',
                    path: urls.productTours(),
                },
                {
                    key: Scene.ProductTour,
                    name: productTour?.name || 'Product tour',
                    path: productTour ? urls.productTour(productTour.id) : undefined,
                },
            ],
        ],
        completionRate: [
            (s) => [s.tourStats],
            (tourStats: ProductTourStats | null): number | null => {
                if (!tourStats || tourStats.shown === 0) {
                    return null
                }
                return Math.round((tourStats.completed / tourStats.shown) * 100)
            },
        ],
        dismissalRate: [
            (s) => [s.tourStats],
            (tourStats: ProductTourStats | null): number | null => {
                if (!tourStats || tourStats.shown === 0) {
                    return null
                }
                return Math.round((tourStats.dismissed / tourStats.shown) * 100)
            },
        ],
        targetingFlagFilters: [
            (s) => [s.productTourForm],
            (productTourForm: ProductTourForm): FeatureFlagFilters | undefined => {
                if (productTourForm.targeting_flag_filters) {
                    return {
                        ...productTourForm.targeting_flag_filters,
                        groups: productTourForm.targeting_flag_filters.groups,
                        multivariate: null,
                        payloads: {},
                    }
                }
                return undefined
            },
        ],
    }),
    urlToAction(({ actions, props }) => ({
        [urls.productTour(props.id)]: (_, searchParams) => {
            if (searchParams.edit) {
                actions.editingProductTour(true)
            }
        },
    })),
    actionToUrl(() => ({
        editingProductTour: ({ editing }) => {
            const searchParams = router.values.searchParams
            if (editing) {
                searchParams['edit'] = true
            } else {
                delete searchParams['edit']
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams]
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadProductTour()
        }
    }),
])
