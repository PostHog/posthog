import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { isNotNil } from 'lib/utils/guards'

import { CompareFilter, WebAnalyticsPropertyFilter, WebAnalyticsPropertyFilters } from '~/queries/schema/schema-general'
import { PropertyFilterBaseValue, PropertyFilterType, PropertyOperator, WebAnalyticsFiltersConfig } from '~/types'

import { DeviceType, INITIAL_WEB_ANALYTICS_FILTER } from './common'
import type { webAnalyticsFilterLogicType } from './webAnalyticsFilterLogicType'

const teamId = window.POSTHOG_APP_CONTEXT?.current_team?.id
const persistConfig = { persist: true, prefix: `${teamId}__` }

const eventFilter = (key: string, value: string | string[]): WebAnalyticsPropertyFilter => ({
    type: PropertyFilterType.Event,
    key,
    value,
    operator: PropertyOperator.Exact,
})

// Event+Exact filters are the subset shared with the live stream view.
export const isLiveStreamFilter = (filter: WebAnalyticsPropertyFilter): boolean =>
    filter.type === PropertyFilterType.Event && filter.operator === PropertyOperator.Exact

export const webAnalyticsFilterLogic = kea<webAnalyticsFilterLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsFilterLogic']),
    connect(() => ({
        values: [
            authorizedUrlListLogic({
                type: AuthorizedUrlListType.WEB_ANALYTICS,
                actionId: null,
                experimentId: null,
                productTourId: null,
            }),
            ['authorizedUrls as rawAuthorizedUrls'],
        ],
    })),
    actions({
        setWebAnalyticsFilters: (webAnalyticsFilters: WebAnalyticsPropertyFilters) => ({ webAnalyticsFilters }),
        togglePropertyFilter: (
            type: PropertyFilterType.Event | PropertyFilterType.Person | PropertyFilterType.Session,
            key: string,
            value: string | number | null,
            tabChange?: {
                graphsTab?: string
                sourceTab?: string
                deviceTab?: string
                pathTab?: string
                geographyTab?: string
                activeHoursTab?: string
            }
        ) => ({ type, key, value, tabChange }),
        setDomainFilter: (domain: string | null) => ({ domain }),
        setDeviceTypeFilter: (deviceType: DeviceType | null) => ({ deviceType }),
        setCountryFilter: (countryCode: string | null) => ({ countryCode }),
        setReferrerFilter: (referrer: string | null) => ({ referrer }),
        setCompareFilter: (compareFilter: CompareFilter) => ({ compareFilter }),
        loadPreset: (filters: WebAnalyticsFiltersConfig) => ({ filters }),
        clearFilters: true,
    }),
    reducers({
        rawWebAnalyticsFilters: [
            INITIAL_WEB_ANALYTICS_FILTER,
            persistConfig,
            {
                setWebAnalyticsFilters: (_, { webAnalyticsFilters }) => webAnalyticsFilters,
                clearFilters: () => INITIAL_WEB_ANALYTICS_FILTER,
                togglePropertyFilter: (oldPropertyFilters, { key, value, type }): WebAnalyticsPropertyFilters => {
                    if (value === null) {
                        // if there's already an isNotSet filter, remove it
                        const isNotSetFilterExists = oldPropertyFilters.some(
                            (f) => f.type === type || f.key === key || f.operator === PropertyOperator.IsNotSet
                        )
                        if (isNotSetFilterExists) {
                            return oldPropertyFilters.filter(
                                (f) => f.type !== type || f.key !== key || f.operator !== PropertyOperator.IsNotSet
                            )
                        }
                        return [
                            ...oldPropertyFilters,
                            {
                                type,
                                key,
                                operator: PropertyOperator.IsNotSet,
                            },
                        ]
                    }

                    const similarFilterExists = oldPropertyFilters.some(
                        (f) => f.type === type && f.key === key && f.operator === PropertyOperator.Exact
                    )

                    if (similarFilterExists) {
                        // if there's already a matching property, turn it off or merge them
                        return oldPropertyFilters
                            .map((f: WebAnalyticsPropertyFilter) => {
                                if (
                                    f.key !== key ||
                                    f.type !== type ||
                                    ![PropertyOperator.Exact, PropertyOperator.IsNotSet].includes(f.operator)
                                ) {
                                    return f
                                }
                                const oldValue = (Array.isArray(f.value) ? f.value : [f.value]).filter(isNotNil)
                                let newValue: PropertyFilterBaseValue[]
                                if (oldValue.includes(value)) {
                                    // If there are multiple values for this filter, reduce that to just the one being clicked
                                    if (oldValue.length > 1) {
                                        newValue = [value]
                                    } else {
                                        return null
                                    }
                                } else {
                                    newValue = [...oldValue, value]
                                }
                                return {
                                    type: PropertyFilterType.Event,
                                    key,
                                    operator: PropertyOperator.Exact,
                                    value: newValue,
                                } as const
                            })
                            .filter(isNotNil)
                    }

                    // no matching property, so add one
                    const newFilter: WebAnalyticsPropertyFilter = {
                        type,
                        key,
                        value,
                        operator: PropertyOperator.Exact,
                    }

                    return [...oldPropertyFilters, newFilter]
                },
                setDomainFilter: (state) => {
                    // the domain and host filters don't interact well, so remove the host filter when the domain filter is set
                    return state.filter((filter) => filter.key !== '$host')
                },
                loadPreset: (_, { filters }) => filters.properties ?? INITIAL_WEB_ANALYTICS_FILTER,
            },
        ],
        domainFilter: [
            null as string | null,
            persistConfig,
            {
                setDomainFilter: (_: string | null, payload: { domain: string | null }) => {
                    const { domain } = payload
                    return domain
                },
                clearFilters: () => null,
                togglePropertyFilter: (state, { key }) => {
                    // the domain and host filters don't interact well, so remove the domain filter when the host filter is set
                    return key === '$host' ? null : state
                },
                setWebAnalyticsFilters: (state, { webAnalyticsFilters }) => {
                    // the domain and host filters don't interact well, so remove the domain filter when the host filter is set
                    if (webAnalyticsFilters.some((f) => f.key === '$host')) {
                        return null
                    }
                    return state
                },
                loadPreset: (_, { filters }) => filters.domainFilter ?? null,
            },
        ],
        deviceTypeFilter: [
            null as DeviceType | null,
            persistConfig,
            {
                setDeviceTypeFilter: (_: DeviceType | null, { deviceType }: { deviceType: DeviceType | null }) =>
                    deviceType,
                clearFilters: () => null,
                loadPreset: (_, { filters }) => (filters.deviceTypeFilter as DeviceType) ?? null,
            },
        ],
        countryFilter: [
            null as string | null,
            persistConfig,
            {
                setCountryFilter: (_: string | null, { countryCode }: { countryCode: string | null }) => countryCode,
                clearFilters: () => null,
                loadPreset: (_, { filters }) => filters.countryFilter ?? null,
            },
        ],
        referrerFilter: [
            null as string | null,
            persistConfig,
            {
                setReferrerFilter: (_: string | null, { referrer }: { referrer: string | null }) => referrer,
                clearFilters: () => null,
                loadPreset: (_, { filters }) => filters.referrerFilter ?? null,
            },
        ],
        compareFilter: [
            { compare: true } as CompareFilter,
            persistConfig,
            {
                setCompareFilter: (_, { compareFilter }) => compareFilter,
                clearFilters: () => ({ compare: true }),
                loadPreset: (_, { filters }) => (filters.compareFilter as CompareFilter) ?? { compare: true },
            },
        ],
    }),
    selectors({
        hasHostFilter: [(s) => [s.rawWebAnalyticsFilters], (filters) => filters.some((f) => f.key === '$host')],
        authorizedDomains: [
            (s) => [s.rawAuthorizedUrls],
            (rawAuthorizedUrls: string[]): string[] => {
                // Normalize URLs to domains:
                // - Convert URLs to domains using url.origin
                // - Deduplicate by hostname+port
                // - Prefer https over http
                const urlsByDomain = new Map<string, URL[]>()

                for (const urlStr of rawAuthorizedUrls) {
                    try {
                        const url = new URL(urlStr)
                        const key = url.host
                        if (!urlsByDomain.has(key)) {
                            urlsByDomain.set(key, [])
                        }
                        urlsByDomain.get(key)!.push(url)
                    } catch {
                        // Skip URLs that can't be parsed
                    }
                }

                return Array.from(urlsByDomain.values()).map((urls) => {
                    const preferredUrl = urls.find((url) => url.protocol === 'https:') ?? urls[0]
                    return preferredUrl.origin
                })
            },
        ],
        validatedDomainFilter: [
            (s) => [s.domainFilter, s.authorizedDomains],
            (domainFilter: string | null, authorizedDomains: string[]): string | null => {
                if (!domainFilter || domainFilter === 'all') {
                    return domainFilter
                }
                if (authorizedDomains.includes(domainFilter)) {
                    return domainFilter
                }

                return null
            },
        ],
        selectedHost: [
            (s) => [s.validatedDomainFilter],
            (domainFilter: string | null): string | null =>
                domainFilter && domainFilter !== 'all' ? domainFilter.replace(/^https?:\/\//, '') : null,
        ],
        // Returns the domain to use for URL construction: selected domain, or single authorized domain if only one exists
        effectiveDomain: [
            (s) => [s.domainFilter, s.authorizedDomains],
            (domainFilter: string | null, authorizedDomains: string[]): string | null => {
                if (domainFilter && domainFilter !== 'all') {
                    return domainFilter
                }
                if (authorizedDomains.length === 1) {
                    return authorizedDomains[0]
                }
                return null
            },
        ],
        liveFilters: [
            (s) => [s.rawWebAnalyticsFilters, s.selectedHost, s.deviceTypeFilter],
            (
                rawWebAnalyticsFilters: WebAnalyticsPropertyFilters,
                host: string | null,
                deviceType: DeviceType | null
            ): WebAnalyticsPropertyFilter[] => {
                const filters: WebAnalyticsPropertyFilter[] = rawWebAnalyticsFilters.filter(isLiveStreamFilter)
                if (host) {
                    filters.push(eventFilter('$host', host))
                }
                if (deviceType === 'Desktop') {
                    filters.push(eventFilter('$device_type', 'Desktop'))
                } else if (deviceType === 'Mobile') {
                    filters.push(eventFilter('$device_type', ['Mobile', 'Tablet']))
                }
                return filters
            },
        ],
    }),
    listeners(({ values }) => ({
        setWebAnalyticsFilters: ({ webAnalyticsFilters }) => {
            const categories = new Set(webAnalyticsFilters.map((f) => f.type))
            for (const category of categories) {
                eventUsageLogic.actions.reportWebAnalyticsFilterApplied({
                    filter_type: 'property',
                    property_filter_category: category,
                    total_filter_count: webAnalyticsFilters.length,
                })
            }
        },
        setDomainFilter: ({ domain }) => {
            const action = domain ? 'reportWebAnalyticsFilterApplied' : 'reportWebAnalyticsFilterRemoved'
            eventUsageLogic.actions[action]({
                filter_type: 'domain',
                total_filter_count: values.rawWebAnalyticsFilters.length,
            })
        },
        setDeviceTypeFilter: ({ deviceType }) => {
            const action = deviceType ? 'reportWebAnalyticsFilterApplied' : 'reportWebAnalyticsFilterRemoved'
            eventUsageLogic.actions[action]({
                filter_type: 'device_type',
                total_filter_count: values.rawWebAnalyticsFilters.length,
            })
        },
        setCountryFilter: ({ countryCode }) => {
            const action = countryCode ? 'reportWebAnalyticsFilterApplied' : 'reportWebAnalyticsFilterRemoved'
            eventUsageLogic.actions[action]({
                filter_type: 'country',
                total_filter_count: values.rawWebAnalyticsFilters.length,
            })
        },
        setReferrerFilter: ({ referrer }) => {
            const action = referrer ? 'reportWebAnalyticsFilterApplied' : 'reportWebAnalyticsFilterRemoved'
            eventUsageLogic.actions[action]({
                filter_type: 'referrer',
                total_filter_count: values.rawWebAnalyticsFilters.length,
            })
        },
        setCompareFilter: ({ compareFilter }) => {
            eventUsageLogic.actions.reportWebAnalyticsCompareToggled({
                enabled: compareFilter?.compare ?? false,
            })
        },
    })),
])
