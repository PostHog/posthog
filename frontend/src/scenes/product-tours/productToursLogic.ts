import Fuse from 'fuse.js'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { uuid } from 'lib/utils'
import { addProductIntent } from 'lib/utils/product-intents'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { deleteFromTree } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    ProductTour,
    ProductTourButtonAction,
    ProductTourContent,
    ProductTourDisplayFrequency,
    ProductTourStepButton,
    ProductTourStepButtons,
    ProgressStatus,
    SurveyPosition,
} from '~/types'

import type { productToursLogicType } from './productToursLogicType'

export const BUTTON_ACTION_OPTIONS: { value: ProductTourButtonAction; label: string }[] = [
    { value: 'dismiss', label: 'Dismiss' },
    { value: 'link', label: 'Open link' },
    { value: 'trigger_tour', label: 'Start tour' },
]

export const TOUR_BUTTON_ACTION_OPTIONS: { value: ProductTourButtonAction; label: string }[] = [
    { value: 'next_step', label: 'Next step' },
    { value: 'previous_step', label: 'Previous step' },
    ...BUTTON_ACTION_OPTIONS,
]

export const DEFAULT_PRIMARY_BUTTON: ProductTourStepButton = {
    text: 'Got it',
    action: 'dismiss',
}

export const DEFAULT_SECONDARY_BUTTON: ProductTourStepButton = {
    text: 'Learn more',
    action: 'link',
    link: '',
}

interface ProductTourDisplayFrequencyOption {
    value: ProductTourDisplayFrequency
    label: string
    tooltip?: string
}

export const BANNER_DISPLAY_FREQUENCY_OPTIONS: ProductTourDisplayFrequencyOption[] = [
    {
        value: 'until_interacted',
        label: 'Until interacted',
        tooltip: 'Shows until user dismisses or interacts',
    },
    {
        value: 'always',
        label: 'Always',
        tooltip: 'Always shows when the rest of your conditions are met. Hides dismiss button.',
    },
]

export const ANNOUNCEMENT_DISPLAY_FREQUENCY_OPTIONS: ProductTourDisplayFrequencyOption[] = [
    { value: 'show_once', label: 'Once', tooltip: "Shows once per user, even if they don't interact" },
    {
        value: 'until_interacted',
        label: 'Until interacted',
        tooltip: 'Shows repeatedly until user clicks a button or dismisses',
    },
]

export function getDisplayFrequencyOptions(tour: Pick<ProductTour, 'content'>): ProductTourDisplayFrequencyOption[] {
    if (isBannerAnnouncement(tour)) {
        return BANNER_DISPLAY_FREQUENCY_OPTIONS
    }
    if (isAnnouncement(tour)) {
        return ANNOUNCEMENT_DISPLAY_FREQUENCY_OPTIONS
    }
    return []
}

export function getDefaultDisplayFrequency(tour: Pick<ProductTour, 'content'>): ProductTourDisplayFrequencyOption {
    const options = getDisplayFrequencyOptions(tour)
    if (options.length === 0) {
        throw new Error(`No defaults found for tour type ${tour.content?.type}`)
    }
    return options[0]
}

export function getDefaultTourStepButtons(stepIndex: number, totalSteps: number): ProductTourStepButtons {
    const isFirstStep = stepIndex === 0
    const isLastStep = stepIndex === totalSteps - 1

    return {
        primary: {
            text: isLastStep ? 'Done' : 'Next',
            action: isLastStep ? 'dismiss' : 'next_step',
        },
        ...(isFirstStep
            ? {}
            : {
                  secondary: {
                      text: 'Back',
                      action: 'previous_step',
                  },
              }),
    }
}

function createDefaultAnnouncementContent(): ProductTourContent {
    return {
        type: 'announcement',
        steps: [
            {
                id: uuid(),
                type: 'modal',
                content: {
                    type: 'doc',
                    content: [
                        {
                            type: 'heading',
                            attrs: { level: 2 },
                            content: [{ type: 'text', text: 'Your announcement title' }],
                        },
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'Add your message here. You can use rich text formatting, images, and more.',
                                },
                            ],
                        },
                    ],
                },
                buttons: {
                    primary: DEFAULT_PRIMARY_BUTTON,
                },
                modalPosition: SurveyPosition.MiddleCenter,
            },
        ],
        appearance: {
            showOverlay: false,
            dismissOnClickOutside: false,
        },
        displayFrequency: 'show_once',
    }
}

function createDefaultBannerContent(): ProductTourContent {
    return {
        type: 'announcement',
        steps: [
            {
                id: uuid(),
                type: 'banner',
                content: {
                    type: 'doc',
                    content: [
                        {
                            type: 'paragraph',
                            content: [
                                {
                                    type: 'text',
                                    text: 'Your banner message here. Keep it short and actionable.',
                                },
                            ],
                        },
                    ],
                },
                bannerConfig: {
                    behavior: 'sticky',
                    action: {
                        type: 'none',
                    },
                },
            },
        ],
        appearance: {
            showOverlay: false,
            dismissOnClickOutside: false,
            whiteLabel: true, // banners simply have no branding
        },
        displayFrequency: 'until_interacted',
    }
}

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

export function isAnnouncement(tour: Pick<ProductTour, 'content'>): boolean {
    return tour.content?.type === 'announcement'
}

export function isBannerAnnouncement(tour: Pick<ProductTour, 'content'>): boolean {
    return isAnnouncement(tour) && tour.content?.steps?.[0]?.type === 'banner'
}

export function isModalAnnouncement(tour: Pick<ProductTour, 'content'>): boolean {
    return isAnnouncement(tour) && tour.content?.steps?.[0]?.type === 'modal'
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
        createAnnouncement: (name: string) => ({ name }),
        createBanner: (name: string) => ({ name }),
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
        createAnnouncement: async ({ name }) => {
            try {
                const announcement = await api.productTours.create({
                    name,
                    content: createDefaultAnnouncementContent(),
                })
                void addProductIntent({
                    product_type: ProductKey.PRODUCT_TOURS,
                    intent_context: ProductIntentContext.PRODUCT_TOUR_CREATED,
                })
                actions.loadProductTours()
                router.actions.push(urls.productTour(announcement.id, 'edit=true&tab=steps'))
            } catch {
                lemonToast.error('Failed to create announcement')
            }
        },
        createBanner: async ({ name }) => {
            try {
                const banner = await api.productTours.create({
                    name,
                    content: createDefaultBannerContent(),
                })
                void addProductIntent({
                    product_type: ProductKey.PRODUCT_TOURS,
                    intent_context: ProductIntentContext.PRODUCT_TOUR_CREATED,
                })
                actions.loadProductTours()
                router.actions.push(urls.productTour(banner.id, 'edit=true&tab=steps'))
            } catch {
                lemonToast.error('Failed to create banner')
            }
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
