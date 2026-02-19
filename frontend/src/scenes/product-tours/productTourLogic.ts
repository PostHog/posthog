import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import isEqual from 'lodash.isequal'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { NEW_FLAG } from 'scenes/feature-flags/featureFlagLogic'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { DateRange } from '~/queries/schema/schema-general'
import {
    Breadcrumb,
    FeatureFlagBasicType,
    FeatureFlagFilters,
    FeatureFlagType,
    ProductTour,
    ProductTourBannerConfig,
    ProductTourContent,
    ProductTourStep,
    ProductTourStepButton,
} from '~/types'

import { DEFAULT_APPEARANCE } from './constants'
import { prepareStepsForRender } from './editor/generateStepHtml'
import type { productTourLogicType } from './productTourLogicType'
import { isAnnouncement, productToursLogic } from './productToursLogic'
import { getUpdatedStepOrderHistory, hasIncompleteTargeting } from './stepUtils'

export const DEFAULT_TARGETING_FILTERS: FeatureFlagType['filters'] = {
    ...NEW_FLAG.filters,
    groups: [{ ...NEW_FLAG.filters.groups[0], rollout_percentage: 100 }],
}

const DATE_FORMAT = 'YYYY-MM-DDTHH:mm:ss'

function getResolvedTourDateRange(
    tour: Pick<ProductTour, 'start_date' | 'created_at' | 'end_date'>,
    dateRange?: DateRange | null
): { fromDate: string; toDate: string } {
    let fromDate = dayjs
        .utc(tour.start_date ?? tour.created_at)
        .startOf('day')
        .format(DATE_FORMAT)
    let toDate = tour.end_date
        ? dayjs.utc(tour.end_date).endOf('day').format(DATE_FORMAT)
        : dayjs.utc().endOf('day').format(DATE_FORMAT)

    if (dateRange?.date_from && dateRange.date_from !== 'all') {
        fromDate = dateStringToDayJs(dateRange.date_from)?.startOf('day').format(DATE_FORMAT) ?? fromDate
    }

    if (dateRange?.date_to) {
        toDate = dateStringToDayJs(dateRange.date_to)?.endOf('day').format(DATE_FORMAT) ?? toDate
    }

    return { fromDate, toDate }
}

function buildHogQLDateFilter(
    tour: Pick<ProductTour, 'start_date' | 'created_at' | 'end_date'>,
    dateRange: DateRange | null,
    timestampColumn = 'timestamp'
): string {
    const { fromDate, toDate } = getResolvedTourDateRange(tour, dateRange)

    return ` AND ${timestampColumn} >= toDateTime('${fromDate}')
        AND ${timestampColumn} <= toDateTime('${toDate}')`
}

/**
 * Escapes special characters in SQL strings to prevent injection
 */
function escapeSqlString(value: string): string {
    return value.replace(/['\\]/g, '\\$&')
}

export type LaunchValidationIssueType = 'missing_element' | 'missing_selector'

export interface LaunchValidationIssue {
    type: LaunchValidationIssueType
    stepNumbers: number[] // 1-based for display
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
    linked_flag: FeatureFlagBasicType | null
    linked_flag_id: number | null
}

const NEW_PRODUCT_TOUR: ProductTourForm = {
    name: '',
    description: '',
    content: { steps: [], appearance: DEFAULT_APPEARANCE },
    auto_launch: false,
    targeting_flag_filters: null,
    linked_flag: null,
    linked_flag_id: null,
}

function tourToFormValues(tour: ProductTour): ProductTourForm {
    const draft = tour.draft_content
    return {
        name: draft?.name ?? tour.name,
        description: draft?.description ?? tour.description,
        content: draft?.content ?? tour.content,
        auto_launch: draft?.auto_launch ?? tour.auto_launch,
        targeting_flag_filters: draft?.targeting_flag_filters ?? tour.targeting_flag_filters,
        linked_flag: tour.linked_flag,
        linked_flag_id: draft?.linked_flag_id ?? tour.linked_flag?.id ?? null,
    }
}

function buildDraftPayload(formValues: ProductTourForm): Record<string, any> {
    const steps = formValues.content.steps ? prepareStepsForRender(formValues.content.steps) : []
    return {
        name: formValues.name,
        description: formValues.description,
        content: {
            ...formValues.content,
            steps,
            step_order_history: getUpdatedStepOrderHistory(
                formValues.content.steps,
                formValues.content.step_order_history
            ),
        },
        auto_launch: formValues.auto_launch,
        targeting_flag_filters: formValues.targeting_flag_filters,
        linked_flag_id: formValues.linked_flag_id,
    }
}

export const productTourLogic = kea<productTourLogicType>([
    path(['scenes', 'product-tours', 'productTourLogic']),
    props({} as ProductTourLogicProps),
    key((props) => props.id),
    connect(() => ({
        actions: [productToursLogic, ['loadProductTours'], eventUsageLogic, ['reportProductTourViewed']],
    })),
    actions({
        editingProductTour: (editing: boolean) => ({ editing }),
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setEditTab: (tab: ProductTourEditTab) => ({ tab }),
        setSelectedStepIndex: (index: number) => ({ index }),
        updateSelectedStep: (updates: Partial<ProductTourStep>) => ({ updates }),
        launchProductTour: true,
        stopProductTour: true,
        resumeProductTour: true,
        publishDraft: true,
        discardDraft: true,
        draftAutoSave: true,
        setDraftActionInProgress: (action: 'publish' | 'discard' | null) => ({ action }),
        openToolbarModal: (toolbarMode?: 'preview' | 'edit') => ({ toolbarMode: toolbarMode ?? 'edit' }),
        closeToolbarModal: true,
        handleToolbarTabVisibility: true,
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

                const dateFilter = buildHogQLDateFilter(values.productTour, values.dateRange)
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
    forms(({ props }) => ({
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

                for (const [index, step] of (content.steps || []).entries()) {
                    let error: string | undefined

                    if (step.type === 'banner') {
                        if (step.bannerConfig?.behavior === 'custom' && !step.bannerConfig?.selector?.trim()) {
                            error = 'Custom banner position requires a CSS selector'
                        } else {
                            error = validateBannerAction(step.bannerConfig?.action, 'Banner click action')
                        }
                    } else {
                        const errorPrefix = content.steps.length > 1 ? `Step ${index + 1} ` : ''

                        error =
                            validateButton(step.buttons?.primary, `${errorPrefix}Primary button`) ||
                            validateButton(step.buttons?.secondary, `${errorPrefix}Secondary button`)
                    }

                    if (error) {
                        errors._form = error
                        break
                    }
                }

                return errors
            },
            submit: async (formValues: ProductTourForm) => {
                if (props.id && props.id !== 'new') {
                    await api.productTours.saveDraft(props.id, buildDraftPayload(formValues))
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
            null as DateRange | null,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        selectedStepIndex: [
            0,
            {
                setSelectedStepIndex: (_, { index }) => index,
            },
        ],
        isToolbarModalOpen: [
            false,
            {
                openToolbarModal: () => true,
                closeToolbarModal: () => false,
            },
        ],
        toolbarMode: [
            'edit' as 'preview' | 'edit',
            {
                openToolbarModal: (_, { toolbarMode }) => toolbarMode,
            },
        ],
        draftSaveStatus: [
            null as 'unsaved' | 'saving' | 'saved' | null,
            {
                draftAutoSave: () => 'unsaved' as const,
                submitProductTourForm: () => 'saving' as const,
                submitProductTourFormSuccess: () => 'saved' as const,
                submitProductTourFormFailure: () => null,
                editingProductTour: () => null,
            },
        ],
        draftActionInProgress: [
            null as 'publish' | 'discard' | null,
            {
                setDraftActionInProgress: (_, { action }) => action,
            },
        ],
    }),
    listeners(({ actions, values, props, cache }) => ({
        updateSelectedStep: ({ updates }) => {
            const steps = values.productTourForm.content?.steps ?? []
            const index = values.selectedStepIndex
            if (index >= 0 && index < steps.length) {
                const newSteps = [...steps]
                newSteps[index] = { ...newSteps[index], ...updates }
                actions.setProductTourFormValue('content', {
                    ...values.productTourForm.content,
                    steps: newSteps,
                })
            }
        },
        submitProductTourFormFailure: () => {
            const errorMessage =
                values.productTourFormAllErrors._form ||
                values.productTourFormAllErrors.name ||
                'Failed to save product tour'
            lemonToast.error(errorMessage)
        },
        publishDraft: async () => {
            if (!values.productTour) {
                return
            }
            actions.setDraftActionInProgress('publish')
            try {
                await api.productTours.publishDraft(values.productTour.id, buildDraftPayload(values.productTourForm))
                lemonToast.success('Product tour saved')
                actions.editingProductTour(false)
                actions.loadProductTour()
                actions.loadProductTours()
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to save product tour')
            } finally {
                actions.setDraftActionInProgress(null)
            }
        },
        discardDraft: async () => {
            if (!values.productTour) {
                return
            }
            actions.setDraftActionInProgress('discard')
            try {
                if (values.hasDraft) {
                    await api.productTours.discardDraft(values.productTour.id)
                    actions.loadProductTour()
                }
                actions.editingProductTour(false)
            } catch (e: any) {
                lemonToast.error(e.detail || 'Failed to discard draft')
            } finally {
                actions.setDraftActionInProgress(null)
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
            if (productTour) {
                actions.reportProductTourViewed(productTour)

                const formValues = tourToFormValues(productTour)
                const incomingPayload = buildDraftPayload(formValues)
                const isOwnEcho = values.isEditingProductTour && isEqual(incomingPayload, cache.lastDraftPayload)
                if (!isOwnEcho) {
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    ;(actions.setProductTourFormValues as any)(formValues)
                    cache.lastDraftPayload = incomingPayload
                }
            }
            if (!values.dateRange) {
                actions.setDateRange({
                    date_from: productTour?.start_date || '-30d',
                    date_to: productTour?.end_date || null,
                })
            } else {
                actions.loadTourStats()
            }
        },
        editingProductTour: ({ editing }) => {
            if (editing && props.id !== 'new') {
                cache.disposables.add(() => {
                    const canFetch = (): boolean =>
                        values.draftSaveStatus !== 'unsaved' && values.draftSaveStatus !== 'saving'

                    if (canFetch()) {
                        actions.loadProductTour()
                    }
                    const intervalId = setInterval(() => {
                        if (canFetch()) {
                            actions.loadProductTour()
                        }
                    }, 3000)
                    return () => clearInterval(intervalId)
                }, 'draftPoll')
            } else if (!editing) {
                cache.disposables.dispose('draftPoll')
            }
        },
        draftAutoSave: async (_, breakpoint) => {
            await breakpoint(1000)
            if (values.isEditingProductTour && values.productTourForm.name) {
                actions.submitProductTourForm()
            }
        },
        setDateRange: () => {
            actions.loadTourStats()
        },
        openToolbarModal: () => {
            cache.disposables.add(
                () => {
                    const handler = (): void => {
                        if (document.visibilityState === 'hidden') {
                            actions.handleToolbarTabVisibility()
                        }
                    }
                    document.addEventListener('visibilitychange', handler)
                    return () => document.removeEventListener('visibilitychange', handler)
                },
                'toolbarModalVisibility',
                { pauseOnPageHidden: false }
            )
        },
        closeToolbarModal: () => {
            cache.disposables.dispose('toolbarModalVisibility')
        },
        handleToolbarTabVisibility: () => {
            actions.closeToolbarModal()
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
        hasCustomTargeting: [
            (s) => [s.targetingFlagFilters],
            (targetingFlagFilters: FeatureFlagFilters | undefined): boolean => {
                return !!targetingFlagFilters && !isEqual(targetingFlagFilters, DEFAULT_TARGETING_FILTERS)
            },
        ],
        entityKeyword: [
            (s) => [s.productTour],
            (productTour: ProductTour | null): string => {
                return productTour && isAnnouncement(productTour) ? 'announcement' : 'tour'
            },
        ],
        hasDraft: [
            (s) => [s.productTour],
            (productTour: ProductTour | null): boolean => {
                return productTour?.has_draft ?? false
            },
        ],
        launchValidationIssues: [
            (s) => [s.productTour],
            (productTour: ProductTour | null): LaunchValidationIssue[] => {
                const steps = productTour?.content?.steps ?? []
                const grouped: Record<LaunchValidationIssueType, number[]> = {
                    missing_element: [],
                    missing_selector: [],
                }
                for (const [index, step] of steps.entries()) {
                    if (hasIncompleteTargeting(step)) {
                        const type: LaunchValidationIssueType =
                            step.elementTargeting === 'manual' ? 'missing_selector' : 'missing_element'
                        grouped[type].push(index + 1)
                    }
                }
                return Object.entries(grouped)
                    .filter(([, steps]) => steps.length > 0)
                    .map(([type, stepNumbers]) => ({ type: type as LaunchValidationIssueType, stepNumbers }))
            },
        ],
    }),
    urlToAction(({ actions, props }) => ({
        [urls.productTour(props.id)]: (_, searchParams) => {
            actions.editingProductTour(!!searchParams.edit)
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
    subscriptions(({ actions, values, cache }) => ({
        productTourForm: (formValues: ProductTourForm) => {
            if (!values.isEditingProductTour || !values.productTour) {
                return
            }
            const payload = buildDraftPayload(formValues)
            if (isEqual(cache.lastDraftPayload, payload)) {
                return
            }
            cache.lastDraftPayload = payload
            actions.draftAutoSave()
        },
    })),
    afterMount(({ actions, props }) => {
        if (props.id !== 'new') {
            actions.loadProductTour()
        }
    }),
])
