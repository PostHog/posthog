import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { DateRange } from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    FeatureFlagFilters,
    ProductTour,
    ProductTourBannerConfig,
    ProductTourContent,
    ProductTourStepButton,
} from '~/types'

import { prepareStepsForRender } from './editor/generateStepHtml'
import type { productTourLogicType } from './productTourLogicType'
import { productToursLogic } from './productToursLogic'

/**
 * Builds a HogQL date filter clause from a DateRange.
 *
 * Handles:
 * - Relative dates like "-30d", "-7d", "-1w", "-1m" → `now() - INTERVAL X UNIT`
 * - ISO dates like "2025-11-10T02:54:31Z" → `toDateTime('2025-11-10 02:54:31')`
 *
 * @param dateRange - The date range to filter by
 * @param timestampColumn - The column name to filter (default: 'timestamp')
 * @returns HogQL WHERE clause fragment (e.g., " AND timestamp >= ...")
 */
function buildHogQLDateFilter(dateRange: DateRange | null, timestampColumn = 'timestamp'): string {
    if (!dateRange) {
        return ''
    }

    const { date_from, date_to } = dateRange
    let filter = ''

    const formatDate = (dateStr: string): string => {
        // For ISO dates, convert to YYYY-MM-DD HH:MM:SS format for ClickHouse
        const date = new Date(dateStr)
        if (!isNaN(date.getTime())) {
            return date.toISOString().replace('T', ' ').replace('Z', '').split('.')[0]
        }
        return dateStr
    }

    const parseRelativeDate = (dateStr: string): { num: number; unit: string } | null => {
        const match = dateStr.match(/^-(\d+)([dwmqy])$/)
        if (!match) {
            return null
        }
        const unitMap: Record<string, string> = { d: 'DAY', w: 'WEEK', m: 'MONTH', q: 'QUARTER', y: 'YEAR' }
        return { num: parseInt(match[1], 10), unit: unitMap[match[2]] || 'DAY' }
    }

    if (date_from) {
        const relative = parseRelativeDate(date_from)
        if (relative) {
            filter += ` AND ${timestampColumn} >= now() - INTERVAL ${relative.num} ${relative.unit}`
        } else {
            filter += ` AND ${timestampColumn} >= toDateTime('${formatDate(date_from)}')`
        }
    }

    if (date_to) {
        const relative = parseRelativeDate(date_to)
        if (relative) {
            filter += ` AND ${timestampColumn} <= now() - INTERVAL ${relative.num} ${relative.unit}`
        } else {
            filter += ` AND ${timestampColumn} <= toDateTime('${formatDate(date_to)}')`
        }
    }

    return filter
}

/**
 * Escapes special characters in SQL strings to prevent injection
 */
function escapeSqlString(value: string): string {
    return value.replace(/['\\]/g, '\\$&')
}

export interface ProductTourLogicProps {
    id: string
}

export enum ProductTourEditTab {
    Configuration = 'configuration',
    Steps = 'steps',
    Customization = 'customization',
}

export interface ProductTourStats {
    // Unique user counts (primary metrics)
    uniqueShown: number
    uniqueCompleted: number
    uniqueDismissed: number
    // Total event counts
    totalShown: number
    totalCompleted: number
    totalDismissed: number
    stepStats: Array<{
        stepOrder: number
        uniqueShown: number
        uniqueCompleted: number
        totalShown: number
        totalCompleted: number
    }>
}

export interface ProductTourForm {
    name: string
    description: string
    content: ProductTourContent
    auto_launch: boolean
    targeting_flag_filters: FeatureFlagFilters | null
}

const NEW_PRODUCT_TOUR: ProductTourForm = {
    name: '',
    description: '',
    content: { steps: [] },
    auto_launch: false,
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
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setEditTab: (tab: ProductTourEditTab) => ({ tab }),
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

                const dateFilter = buildHogQLDateFilter(values.dateRange)
                const escapedTourId = escapeSqlString(props.id)

                // Query for overall tour stats with unique and total counts
                const tourStatsQuery = `
                    SELECT
                        event,
                        count() as total_count,
                        uniq(distinct_id) as unique_count
                    FROM events
                    WHERE event IN ('product tour shown', 'product tour completed', 'product tour dismissed')
                        AND properties.$product_tour_id = '${escapedTourId}'
                        ${dateFilter}
                    GROUP BY event
                `

                // Query for step-level stats with unique and total counts
                const stepStatsQuery = `
                    SELECT
                        JSONExtractInt(properties, '$product_tour_step_order') as step_order,
                        event,
                        count() as total_count,
                        uniq(distinct_id) as unique_count
                    FROM events
                    WHERE event IN ('product tour step shown', 'product tour step completed')
                        AND properties.$product_tour_id = '${escapedTourId}'
                        ${dateFilter}
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
                    let uniqueShown = 0,
                        uniqueCompleted = 0,
                        uniqueDismissed = 0
                    let totalShown = 0,
                        totalCompleted = 0,
                        totalDismissed = 0

                    for (const [event, totalCount, uniqueCount] of tourResults) {
                        if (event === 'product tour shown') {
                            totalShown = totalCount
                            uniqueShown = uniqueCount
                        } else if (event === 'product tour completed') {
                            totalCompleted = totalCount
                            uniqueCompleted = uniqueCount
                        } else if (event === 'product tour dismissed') {
                            totalDismissed = totalCount
                            uniqueDismissed = uniqueCount
                        }
                    }

                    // Process step stats
                    const stepStatsMap = new Map<
                        number,
                        { uniqueShown: number; uniqueCompleted: number; totalShown: number; totalCompleted: number }
                    >()
                    for (const [stepOrder, event, totalCount, uniqueCount] of stepResults) {
                        if (!stepStatsMap.has(stepOrder)) {
                            stepStatsMap.set(stepOrder, {
                                uniqueShown: 0,
                                uniqueCompleted: 0,
                                totalShown: 0,
                                totalCompleted: 0,
                            })
                        }
                        const step = stepStatsMap.get(stepOrder)!
                        if (event === 'product tour step shown') {
                            step.totalShown = totalCount
                            step.uniqueShown = uniqueCount
                        } else if (event === 'product tour step completed') {
                            step.totalCompleted = totalCount
                            step.uniqueCompleted = uniqueCount
                        }
                    }

                    const stepStats = Array.from(stepStatsMap.entries())
                        .sort(([a], [b]) => a - b)
                        .map(([stepOrder, stats]) => ({
                            stepOrder,
                            ...stats,
                        }))

                    return {
                        uniqueShown,
                        uniqueCompleted,
                        uniqueDismissed,
                        totalShown,
                        totalCompleted,
                        totalDismissed,
                        stepStats,
                    }
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
            alwaysShowErrors: true,
            errors: ({ name, content }: ProductTourForm) => {
                const errors: Record<string, string | undefined> = {
                    name: !name ? 'Name is required' : undefined,
                }

                const validateButton = (
                    button: ProductTourStepButton | undefined,
                    errorLabel: string
                ): string | undefined => {
                    if (!button?.action) {
                        return undefined
                    }
                    if (!button.text?.trim()) {
                        return `${errorLabel} requires a label`
                    }
                    if (button.action === 'link' && !button.link?.trim()) {
                        return `${errorLabel} requires a URL`
                    }
                    if (button.action === 'trigger_tour' && !button.tourId) {
                        return `${errorLabel} requires a tour selection`
                    }
                    return undefined
                }

                const validateBannerAction = (
                    action: ProductTourBannerConfig['action'] | undefined,
                    errorLabel: string
                ): string | undefined => {
                    if (!action?.type) {
                        return undefined
                    }
                    if (action.type === 'link' && !action.link?.trim()) {
                        return `${errorLabel} requires a URL`
                    }
                    if (action.type === 'trigger_tour' && !action.tourId) {
                        return `${errorLabel} requires a tour selection`
                    }
                    return undefined
                }

                for (const step of content.steps || []) {
                    const error =
                        step.type === 'banner'
                            ? validateBannerAction(step.bannerConfig?.action, 'Banner click action')
                            : validateButton(step.buttons?.primary, 'Primary button') ||
                              validateButton(step.buttons?.secondary, 'Secondary button')

                    if (error) {
                        errors._form = error
                        break
                    }
                }

                return errors
            },
            submit: async (formValues: ProductTourForm) => {
                const processedContent: ProductTourContent = {
                    ...formValues.content,
                    steps: formValues.content.steps ? prepareStepsForRender(formValues.content.steps) : [],
                }

                const payload = {
                    name: formValues.name,
                    description: formValues.description,
                    content: processedContent,
                    auto_launch: formValues.auto_launch,
                    targeting_flag_filters: formValues.targeting_flag_filters,
                }

                if (props.id && props.id !== 'new') {
                    await api.productTours.update(props.id, payload)
                    lemonToast.success('Product tour updated')
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
        editTab: [
            ProductTourEditTab.Configuration as ProductTourEditTab,
            {
                setEditTab: (_, { tab }) => tab,
            },
        ],
        dateRange: [
            { date_from: '-30d', date_to: null } as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        submitProductTourFormSuccess: () => {
            // don't navigate away if we're on steps page, it's a weird UX
            if (values.editTab !== ProductTourEditTab.Steps) {
                actions.editingProductTour(false)
            }
        },
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
            // Set date range to start from tour's start_date (or keep default -30d)
            // This will trigger loadTourStats via the setDateRange listener
            if (productTour?.start_date) {
                actions.setDateRange({
                    date_from: productTour.start_date,
                    date_to: null,
                })
            } else {
                // No start_date, load stats with default date range
                actions.loadTourStats()
            }
            // Populate form with loaded data
            if (productTour) {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                ;(actions.setProductTourFormValues as any)({
                    name: productTour.name,
                    description: productTour.description,
                    content: productTour.content,
                    auto_launch: productTour.auto_launch,
                    targeting_flag_filters: productTour.targeting_flag_filters,
                })
            }
        },
        editingProductTour: ({ editing }) => {
            if (editing && values.productTour) {
                // Reset form to current tour values when entering edit mode
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                ;(actions.setProductTourFormValues as any)({
                    name: values.productTour.name,
                    description: values.productTour.description,
                    content: values.productTour.content,
                    auto_launch: values.productTour.auto_launch,
                    targeting_flag_filters: values.productTour.targeting_flag_filters,
                })
            }
        },
        setDateRange: () => {
            actions.loadTourStats()
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
            if (searchParams.tab) {
                actions.setEditTab(searchParams.tab as ProductTourEditTab)
            }
        },
    })),
    actionToUrl(({ values }) => ({
        editingProductTour: ({ editing }) => {
            const searchParams = { ...router.values.searchParams }
            if (editing) {
                searchParams['edit'] = 'true'
            } else {
                delete searchParams['edit']
                delete searchParams['tab']
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams]
        },
        setEditTab: () => {
            // Replace history instead of pushing for tab changes
            return [
                router.values.location.pathname,
                { ...router.values.searchParams, tab: values.editTab },
                router.values.hashParams,
                { replace: true },
            ]
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadProductTour()
        }
    }),
])
