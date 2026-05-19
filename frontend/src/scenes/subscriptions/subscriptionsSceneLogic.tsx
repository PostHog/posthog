import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { Sorting } from '@posthog/lemon-ui'

import { runSubscriptionTestDelivery } from 'lib/components/Subscriptions/runSubscriptionTestDelivery'
import { toggleSubscriptionEnabled } from 'lib/components/Subscriptions/toggleSubscriptionEnabled'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { subscriptionsList, subscriptionsTestDeliveryCreate } from '~/generated/core/api'
import {
    SubscriptionsListResourceType,
    TargetTypeEnumApi,
    type PaginatedSubscriptionListApi,
    type SubscriptionsListTargetType,
} from '~/generated/core/api.schemas'
import { Breadcrumb } from '~/types'

import type { subscriptionsSceneLogicType } from './subscriptionsSceneLogicType'

const PAGE_SIZE = 20

export enum SubscriptionsTab {
    All = 'all',
    Mine = 'mine',
    Dashboard = 'dashboard',
    Insight = 'insight',
}

/** Return type is full `SubscriptionsTab` so Kea typegen does not collapse state to the `All` literal. */
function getInitialSubscriptionsTab(): SubscriptionsTab {
    return SubscriptionsTab.All
}

/** Query keys owned by the subscriptions list scene (merged into the router; other params are preserved). */
const SUBSCRIPTIONS_URL_KEYS = ['tab', 'search', 'created_by', 'target_type', 'page'] as const

/** Router may coerce numeric-looking query values; keep text fields as strings. */
function urlSearchParamToString(value: unknown): string {
    return `${value ?? ''}`
}

export interface SubscriptionsQueryFromUrl {
    tab: SubscriptionsTab
    search: string
    createdByUuid: string | null
    targetTypeFilter: SubscriptionsListTargetType | null
    page: number
}

function parseSubscriptionsSearchParams(searchParams: Record<string, unknown>): SubscriptionsQueryFromUrl {
    const rawTab = searchParams['tab']
    const tab: SubscriptionsTab =
        rawTab === SubscriptionsTab.Mine || rawTab === SubscriptionsTab.Dashboard || rawTab === SubscriptionsTab.Insight
            ? rawTab
            : SubscriptionsTab.All

    const search = urlSearchParamToString(searchParams['search'])

    let createdByUuid: string | null =
        typeof searchParams['created_by'] === 'string' ? searchParams['created_by'] : null
    if (tab === SubscriptionsTab.Mine) {
        createdByUuid = null
    }

    const ttRaw = searchParams['target_type']
    const targetTypeFilter: SubscriptionsListTargetType | null =
        ttRaw === TargetTypeEnumApi.Email || ttRaw === TargetTypeEnumApi.Slack || ttRaw === TargetTypeEnumApi.Webhook
            ? ttRaw
            : null

    let page = 1
    const pageRaw = searchParams['page']
    if (pageRaw !== undefined && pageRaw !== null && `${pageRaw}` !== '') {
        const n = parseInt(String(pageRaw), 10)
        if (Number.isFinite(n) && n >= 1) {
            page = n
        }
    }

    return { tab, search, createdByUuid, targetTypeFilter, page }
}

function buildSubscriptionUrlParams(values: {
    currentTab: SubscriptionsTab
    search: string
    createdByUuid: string | null
    targetTypeFilter: SubscriptionsListTargetType | null
    page: number
}): Record<string, string> {
    const out: Record<string, string> = {}
    if (values.currentTab !== SubscriptionsTab.All) {
        out.tab = values.currentTab
    }
    const q = values.search.trim()
    if (q) {
        out.search = q
    }
    if (values.currentTab !== SubscriptionsTab.Mine && values.createdByUuid) {
        out.created_by = values.createdByUuid
    }
    if (values.targetTypeFilter) {
        out.target_type = values.targetTypeFilter
    }
    if (values.page > 1) {
        out.page = String(values.page)
    }
    return out
}

function mergeSubscriptionRouterSearchParams(
    current: Record<string, any>,
    values: {
        currentTab: SubscriptionsTab
        search: string
        createdByUuid: string | null
        targetTypeFilter: SubscriptionsListTargetType | null
        page: number
    }
): Record<string, any> {
    const next = { ...current }
    for (const k of SUBSCRIPTIONS_URL_KEYS) {
        delete next[k]
    }
    Object.assign(next, buildSubscriptionUrlParams(values))
    return next
}

function subscriptionRouterSearchParamsEqual(
    current: Record<string, any>,
    values: {
        currentTab: SubscriptionsTab
        search: string
        createdByUuid: string | null
        targetTypeFilter: SubscriptionsListTargetType | null
        page: number
    }
): boolean {
    const desired = buildSubscriptionUrlParams(values)
    for (const k of SUBSCRIPTIONS_URL_KEYS) {
        const cur = current[k] != null && current[k] !== '' ? String(current[k]) : ''
        const des = desired[k] ?? ''
        if (cur !== des) {
            return false
        }
    }
    return true
}

function subscriptionsListStateEqual(
    parsed: SubscriptionsQueryFromUrl,
    values: {
        currentTab: SubscriptionsTab
        search: string
        createdByUuid: string | null
        targetTypeFilter: SubscriptionsListTargetType | null
        page: number
    }
): boolean {
    return (
        parsed.tab === values.currentTab &&
        parsed.search === values.search &&
        (parsed.createdByUuid ?? '') === (values.createdByUuid ?? '') &&
        (parsed.targetTypeFilter ?? null) === (values.targetTypeFilter ?? null) &&
        parsed.page === values.page
    )
}

/** LemonTable columnKey → DRF `ordering` field (see SubscriptionViewSet.ordering_fields). */
function buildSubscriptionsListOrdering(sorting: Sorting | null): string {
    if (!sorting) {
        return '-created_at'
    }
    const fieldByColumnKey: Record<string, string> = {
        next_delivery_date: 'next_delivery_date',
        created_at: 'created_at',
        created_by: 'created_by__email',
        name: 'title',
    }
    const field = fieldByColumnKey[sorting.columnKey]
    if (!field) {
        return '-created_at'
    }
    const dir = sorting.order === -1 ? '-' : ''
    return `${dir}${field}`
}

export const subscriptionsSceneLogic = kea<subscriptionsSceneLogicType>([
    path(['scenes', 'subscriptions', 'subscriptionsSceneLogic']),
    tabAwareScene(),
    connect(() => ({ values: [userLogic, ['user']] })),
    actions({
        loadSubscriptions: true,
        setSearch: (search: string) => ({ search }),
        setPage: (page: number) => ({ page }),
        setCreatedByFilter: (uuid: string | null) => ({ uuid }),
        setCurrentTab: (tab: SubscriptionsTab) => ({ tab }),
        setSubscriptionsSorting: (sorting: Sorting | null) => ({ sorting }),
        setTargetTypeFilter: (targetType: SubscriptionsListTargetType | null) => ({ targetType }),
        applySubscriptionsQueryFromUrl: (query: SubscriptionsQueryFromUrl) => ({ query }),
        deleteSubscriptionSuccess: true,
        deliverSubscription: (id: number) => ({ id }),
        deliverSubscriptionSuccess: true,
        deliverSubscriptionFailure: true,
        setSubscriptionEnabled: (id: number, enabled: boolean) => ({ id, enabled }),
        setSubscriptionEnabledSuccess: true,
        setSubscriptionEnabledFailure: true,
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
                applySubscriptionsQueryFromUrl: (_, { query }) => query.search,
            },
        ],
        createdByUuid: [
            null as string | null,
            {
                setCreatedByFilter: (_, { uuid }) => uuid,
                setCurrentTab: (state, { tab }) => (tab === SubscriptionsTab.Mine ? null : state),
                applySubscriptionsQueryFromUrl: (_, { query }) =>
                    query.tab === SubscriptionsTab.Mine ? null : query.createdByUuid,
            },
        ],
        currentTab: [
            getInitialSubscriptionsTab(),
            {
                setCurrentTab: (_, { tab }) => tab,
                applySubscriptionsQueryFromUrl: (_, { query }) => query.tab,
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => page,
                setSearch: () => 1,
                setCreatedByFilter: () => 1,
                setCurrentTab: () => 1,
                setSubscriptionsSorting: () => 1,
                setTargetTypeFilter: () => 1,
                deleteSubscriptionSuccess: () => 1,
                applySubscriptionsQueryFromUrl: (_, { query }) => query.page,
            },
        ],
        subscriptionsSorting: [
            null as Sorting | null,
            {
                setSubscriptionsSorting: (_, { sorting }) => sorting,
            },
        ],
        targetTypeFilter: [
            null as SubscriptionsListTargetType | null,
            {
                setTargetTypeFilter: (_, { targetType }) => targetType,
                applySubscriptionsQueryFromUrl: (_, { query }) => query.targetTypeFilter,
            },
        ],
        /**
         * True after `setSearch` until the debounced list request finishes. Avoids treating stale
         * empty `subscriptionsResponse` as "no subscriptions in project" when filters were cleared.
         */
        subscriptionsListAwaitingDebouncedFetch: [
            false,
            {
                setSearch: () => true,
                loadSubscriptionsSuccess: () => false,
                loadSubscriptionsFailure: () => false,
            },
        ],
        deliveringSubscriptionId: [
            null as number | null,
            {
                deliverSubscription: (_, { id }) => id,
                deliverSubscriptionSuccess: () => null,
                deliverSubscriptionFailure: () => null,
            },
        ],
        // Tracks the subscription whose Pause/Resume PATCH is in flight so the row's
        // menu item can show a busy state and prevent double-clicks.
        togglingEnabledId: [
            null as number | null,
            {
                setSubscriptionEnabled: (_, { id }) => id,
                setSubscriptionEnabledSuccess: () => null,
                setSubscriptionEnabledFailure: () => null,
            },
        ],
    }),
    loaders(({ values }) => ({
        subscriptionsResponse: [
            null as PaginatedSubscriptionListApi | null,
            {
                loadSubscriptions: async () => {
                    const projectId = String(getCurrentTeamId())
                    let resourceType: SubscriptionsListResourceType | undefined
                    if (values.currentTab === SubscriptionsTab.Dashboard) {
                        resourceType = SubscriptionsListResourceType.Dashboard
                    } else if (values.currentTab === SubscriptionsTab.Insight) {
                        resourceType = SubscriptionsListResourceType.Insight
                    }
                    const createdBy =
                        values.currentTab === SubscriptionsTab.Mine
                            ? values.user?.uuid
                            : values.createdByUuid || undefined
                    const ordering = buildSubscriptionsListOrdering(values.subscriptionsSorting)
                    return await subscriptionsList(projectId, {
                        limit: PAGE_SIZE,
                        offset: (values.page - 1) * PAGE_SIZE,
                        search: values.search.trim() || undefined,
                        ordering,
                        created_by: createdBy,
                        resource_type: resourceType,
                        target_type: values.targetTypeFilter ?? undefined,
                    })
                },
            },
        ],
    })),
    selectors({
        subscriptions: [
            (s) => [s.subscriptionsResponse],
            (subscriptionsResponse: PaginatedSubscriptionListApi | null) => subscriptionsResponse?.results ?? [],
        ],
        subscriptionsLoading: [
            (s) => [s.subscriptionsResponseLoading],
            (subscriptionsResponseLoading: boolean) => Boolean(subscriptionsResponseLoading),
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Subscriptions,
                    name: sceneConfigurations[Scene.Subscriptions].name,
                    iconType: sceneConfigurations[Scene.Subscriptions].iconType || 'default_icon_type',
                },
            ],
        ],
    }),
    selectors(({ actions }) => ({
        pagination: [
            (s) => [s.page, s.subscriptionsResponse],
            (page: number, subscriptionsResponse: PaginatedSubscriptionListApi | null) => {
                const count = subscriptionsResponse?.count ?? 0
                // usePagination uses `entryCount || null`; 0 is treated as missing and breaks pageCount / next button.
                // LemonTable shows "No …" when the page is empty, so inflating 0→1 only satisfies the hook.
                const entryCount = Math.max(count, 1)
                return {
                    controlled: true,
                    pageSize: PAGE_SIZE,
                    currentPage: page,
                    entryCount,
                    onBackward: () => actions.setPage(page - 1),
                    onForward: () => actions.setPage(page + 1),
                }
            },
        ],
    })),
    listeners(({ actions }) => ({
        setSearch: async (_, breakpoint) => {
            await breakpoint(300)
            actions.loadSubscriptions()
        },
        setPage: () => actions.loadSubscriptions(),
        setCreatedByFilter: () => actions.loadSubscriptions(),
        setCurrentTab: () => actions.loadSubscriptions(),
        setSubscriptionsSorting: () => actions.loadSubscriptions(),
        setTargetTypeFilter: () => actions.loadSubscriptions(),
        applySubscriptionsQueryFromUrl: () => actions.loadSubscriptions(),
        deleteSubscriptionSuccess: () => actions.loadSubscriptions(),
        deliverSubscription: async ({ id }) => {
            const result = await runSubscriptionTestDelivery(() =>
                subscriptionsTestDeliveryCreate(String(getCurrentTeamId()), id)
            )
            if (result === 'success') {
                actions.deliverSubscriptionSuccess()
            } else {
                actions.deliverSubscriptionFailure()
            }
        },
        setSubscriptionEnabled: async ({ id, enabled }) => {
            const ok = await toggleSubscriptionEnabled(id, enabled)
            if (ok) {
                actions.setSubscriptionEnabledSuccess()
            } else {
                actions.setSubscriptionEnabledFailure()
            }
        },
        setSubscriptionEnabledSuccess: () => actions.loadSubscriptions(),
    })),
    tabAwareActionToUrl(({ values }) => {
        const syncUrl = (
            replace: boolean
        ): [string, Record<string, any>, Record<string, unknown> | undefined, { replace: boolean }] | undefined => {
            const subscriptionValues = {
                currentTab: values.currentTab,
                search: values.search,
                createdByUuid: values.createdByUuid,
                targetTypeFilter: values.targetTypeFilter,
                page: values.page,
            }
            const pathname = router.values.location.pathname
            if (pathname !== urls.subscriptions()) {
                return
            }
            if (subscriptionRouterSearchParamsEqual(router.values.searchParams, subscriptionValues)) {
                return
            }
            const next = mergeSubscriptionRouterSearchParams(router.values.searchParams, subscriptionValues)
            return [pathname, next, router.values.hashParams, { replace }] as const
        }
        return {
            setSearch: () => syncUrl(true),
            setCreatedByFilter: () => syncUrl(true),
            setTargetTypeFilter: () => syncUrl(true),
            setPage: () => syncUrl(true),
            setCurrentTab: () => syncUrl(false),
        }
    }),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.subscriptions()]: (_, searchParams) => {
            const parsed = parseSubscriptionsSearchParams(searchParams)
            const listState = {
                currentTab: values.currentTab,
                search: values.search,
                createdByUuid: values.createdByUuid,
                targetTypeFilter: values.targetTypeFilter,
                page: values.page,
            }
            if (subscriptionsListStateEqual(parsed, listState)) {
                return
            }
            actions.applySubscriptionsQueryFromUrl(parsed)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSubscriptions()
    }),
])
