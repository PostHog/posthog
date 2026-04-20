import equal from 'fast-deep-equal'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { hashCodeForString } from 'lib/utils'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { deduplicateEvents } from 'scenes/activity/live/deduplicateEvents'
import { teamLogic } from 'scenes/teamLogic'
import { webAnalyticsFilterLogic } from 'scenes/web-analytics/webAnalyticsFilterLogic'

import { performQuery } from '~/queries/query'
import {
    HogQLQuery,
    HogQLQueryResponse,
    NodeKind,
    TrendsQuery,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { BaseMathType, LiveEvent, PropertyFilterType, PropertyOperator } from '~/types'

import { createStreamConnection } from './createStreamConnection'
import { LiveMetricsSlidingWindow } from './LiveMetricsSlidingWindow'
import type { liveWebAnalyticsMetricsLogicType } from './liveWebAnalyticsMetricsLogicType'
import {
    BrowserBreakdownItem,
    ChartDataPoint,
    CountryBreakdownItem,
    DeviceBreakdownItem,
    DIRECT_REFERRER,
    LiveGeoEvent,
    PathItem,
    ReferrerItem,
    SlidingWindowBucket,
} from './LiveWebAnalyticsMetricsTypes'
import {
    FILTERED_LIVE_USER_WINDOW_SECONDS,
    pruneRecentUsersByLastSeen,
    upsertRecentUsersByLastSeenFromEvents,
} from './recentUsersByLastSeen'

const ERROR_TOAST_ID = 'live-pageviews-error'
const RECONNECT_TOAST_ID = 'live-pageviews-reconnect'
const BUCKET_WINDOW_MINUTES = 30
const FLUSH_INTERVAL_MS = 300
const COOKIELESS_TRANSFORM_PREFIX = 'cookieless_transform'
const COOKIELESS_TRANSFORM_SEPARATOR = '|||'
const COUNTRY_BREAKDOWN_LIMIT = 6

export const liveWebAnalyticsMetricsLogic = kea<liveWebAnalyticsMetricsLogicType>([
    path(['scenes', 'web-analytics', 'livePageviewsLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeam'],
            featureFlagLogic,
            ['featureFlags'],
            webAnalyticsFilterLogic,
            ['selectedHost as rawSelectedHost'],
        ],
    })),
    actions(() => ({
        addEvents: (events: LiveEvent[], newerThan: Date) => ({ events, newerThan }),
        addGeoEvents: (events: LiveGeoEvent[]) => ({ events }),
        setInitialData: (
            buckets: { timestamp: number; bucket: SlidingWindowBucket }[],
            recentUsersByLastSeen: [string, number][]
        ) => ({ buckets, recentUsersByLastSeen }),
        setIsLoading: (loading: boolean) => ({ loading }),
        loadInitialData: true,
        updateConnection: true,
        updateGeoConnection: true,
        tickCurrentMinute: true,
        tickLiveUserCount: true,
        pauseStream: true,
        resumeStream: true,
        clearRecentEvents: true,
        clearFilteredLiveUsers: true,
    })),
    reducers({
        slidingWindow: [
            new LiveMetricsSlidingWindow(BUCKET_WINDOW_MINUTES),
            {
                setInitialData: (_, { buckets }) => {
                    const freshWindow = new LiveMetricsSlidingWindow(BUCKET_WINDOW_MINUTES)
                    for (const { timestamp, bucket } of buckets) {
                        freshWindow.extendBucketData(timestamp / 1000, bucket)
                    }
                    freshWindow.prune()
                    return freshWindow
                },
                addEvents: (window, { events, newerThan }) => {
                    for (const event of events) {
                        const eventTs = new Date(event.timestamp).getTime() / 1000
                        const newerThanTs = newerThan.getTime() / 1000

                        if (eventTs > newerThanTs) {
                            const pathname = event.properties?.$pathname
                            const deviceType = event.properties?.$device_type
                            const deviceId = event.properties?.$device_id
                            const browser = event.properties?.$browser
                            const referringDomain = event.properties?.$referring_domain

                            // For cookieless events, device_id isn't set before preprocessing
                            // so we create a device key from IP + user agent
                            let deviceKey = deviceId
                            if (!deviceKey || deviceKey === '$posthog_cookieless') {
                                const ip = event.properties?.$ip ?? ''
                                const ua = event.properties?.$raw_user_agent ?? ''
                                deviceKey = `cookieless_${hashCodeForString(ip + ua)}`
                            }

                            const isPageview = event.event === '$pageview'
                            const normalizedReferrer =
                                isPageview &&
                                referringDomain &&
                                referringDomain !== DIRECT_REFERRER &&
                                referringDomain !== ''
                                    ? referringDomain
                                    : isPageview
                                      ? DIRECT_REFERRER
                                      : undefined

                            window.addDataPoint(eventTs, event.distinct_id, {
                                pageviews: isPageview ? 1 : 0,
                                device: deviceType ? { deviceId: deviceKey, deviceType } : undefined,
                                browser: browser ? { deviceId: deviceKey, browserType: browser } : undefined,
                                pathname: isPageview ? pathname : undefined,
                                referringDomain: normalizedReferrer,
                            })
                        }
                    }

                    window.prune()
                    return window
                },
                addGeoEvents: (window, { events }) => {
                    const nowTs = Date.now() / 1000
                    for (const event of events) {
                        if (event.countryCode) {
                            const distinctId = event.distinctId
                            window.addGeoDataPoint(nowTs, event.countryCode, distinctId)
                        }
                    }
                    window.prune()
                    return window
                },
            },
        ],
        eventsVersion: [
            0,
            {
                setInitialData: (v) => v + 1,
                addEvents: (v) => v + 1,
                tickCurrentMinute: (v) => v + 1,
            },
        ],
        recentUsersByLastSeen: [
            new Map<string, number>(),
            {
                setInitialData: (_, { recentUsersByLastSeen }) => new Map(recentUsersByLastSeen),
                addEvents: (state, { events, newerThan }) =>
                    upsertRecentUsersByLastSeenFromEvents(state, events, newerThan),
                tickLiveUserCount: (state) => pruneRecentUsersByLastSeen(state, Date.now() / 1000),
                clearFilteredLiveUsers: () => new Map<string, number>(),
            },
        ],
        geoVersion: [
            0,
            {
                setInitialData: (v) => v + 1,
                addGeoEvents: (v) => v + 1,
            },
        ],
        isLoading: [
            true,
            {
                setIsLoading: (_, { loading }) => loading,
            },
        ],
        recentEvents: [
            [] as LiveEvent[],
            {
                addEvents: (state, { events }) => deduplicateEvents(state, events, 50),
                clearRecentEvents: () => [],
            },
        ],
    }),
    selectors({
        chartData: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): ChartDataPoint[] => {
                const bucketMap = new Map(slidingWindow.getSortedBuckets())
                const result: ChartDataPoint[] = []

                const currentBucketTs = Math.floor(Date.now() / 60000) * 60
                for (let i = BUCKET_WINDOW_MINUTES - 1; i >= 0; i--) {
                    const ts = currentBucketTs - i * 60
                    const bucket = bucketMap.get(ts)

                    result.push({
                        minute: dayjs.unix(ts).format('HH:mm'),
                        timestamp: ts * 1000,
                        users: bucket?.uniqueUsers.size ?? 0,
                        newUsers: bucket?.newUserCount ?? 0,
                        returningUsers: bucket?.returningUserCount ?? 0,
                        pageviews: bucket?.pageviews ?? 0,
                    })
                }

                return result
            },
            { resultEqualityCheck: equal },
        ],
        deviceBreakdown: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): DeviceBreakdownItem[] => slidingWindow.getDeviceBreakdown(),
            { resultEqualityCheck: equal },
        ],
        browserBreakdown: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): BrowserBreakdownItem[] => slidingWindow.getBrowserBreakdown(6),
            { resultEqualityCheck: equal },
        ],
        countryBreakdown: [
            (s) => [s.slidingWindow, s.geoVersion],
            (slidingWindow: LiveMetricsSlidingWindow): CountryBreakdownItem[] => slidingWindow.getCountryBreakdown(),
            { resultEqualityCheck: equal },
        ],
        topCountryBreakdown: [
            (s) => [s.countryBreakdown],
            (countryBreakdown: CountryBreakdownItem[]): CountryBreakdownItem[] => {
                if (countryBreakdown.length <= COUNTRY_BREAKDOWN_LIMIT) {
                    return countryBreakdown
                }
                const top = countryBreakdown.slice(0, COUNTRY_BREAKDOWN_LIMIT)
                const rest = countryBreakdown.slice(COUNTRY_BREAKDOWN_LIMIT)
                const othersCount = rest.reduce((sum, item) => sum + item.count, 0)
                if (othersCount === 0) {
                    return top
                }
                const othersPercentage = rest.reduce((sum, item) => sum + item.percentage, 0)
                return [
                    ...top,
                    {
                        country: 'Other',
                        count: othersCount,
                        percentage: othersPercentage,
                    },
                ]
            },
            { resultEqualityCheck: equal },
        ],
        topPaths: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): PathItem[] => slidingWindow.getTopPaths(10),
            { resultEqualityCheck: equal },
        ],
        topReferrers: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): ReferrerItem[] => slidingWindow.getTopReferrers(10),
            { resultEqualityCheck: equal },
        ],
        totalPageviews: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalPageviews(),
        ],
        totalUniqueVisitors: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalUniqueUsers(),
        ],
        totalBrowsers: [
            (s) => [s.slidingWindow, s.eventsVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalBrowsers(),
        ],
        liveUserCount: [
            (s) => [s.recentUsersByLastSeen],
            (recentUsersByLastSeen: Map<string, number>): number => recentUsersByLastSeen.size,
        ],
        selectedHost: [
            (s) => [s.rawSelectedHost, s.featureFlags],
            (rawSelectedHost: string | null, featureFlags: FeatureFlagsSet): string | null =>
                featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_LIVE_DOMAIN_FILTER] ? rawSelectedHost : null,
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        pauseStream: () => {
            cache.eventsConnection?.abort()
            cache.geoConnection?.abort()
            cache.batch = []
            cache.geoBatch = []
            stopFlushInterval(cache as FlushCache)
            if (cache.liveUserCountInterval) {
                clearInterval(cache.liveUserCountInterval)
                cache.liveUserCountInterval = null
            }
        },
        resumeStream: () => {
            if (cache.hasInitialized) {
                lemonToast.info('Refreshing live data...', {
                    toastId: RECONNECT_TOAST_ID,
                    autoClose: 2000,
                })
            }
            startFlushInterval(cache as FlushCache, actions as FlushActions)
            if (!cache.liveUserCountInterval) {
                // Drives the "Users online" count so users drop off within ~5s of leaving the 60s window
                cache.liveUserCountInterval = setInterval(() => {
                    actions.tickLiveUserCount()
                }, 5000)
            }
            actions.loadInitialData()
        },
        loadInitialData: async () => {
            actions.setIsLoading(true)

            try {
                const now = Date.now()
                const dateFrom = new Date(now - BUCKET_WINDOW_MINUTES * 60 * 1000)
                const handoff = new Date(now)

                // The SSE stream will drop any events older than this value
                // Those values will be retrieved by the HogQL queries instead
                cache.newerThan = handoff

                actions.updateConnection()
                actions.updateGeoConnection()
                const [
                    usersPageviewsResponse,
                    deviceResponse,
                    browserResponse,
                    pathsResponse,
                    referrerResponse,
                    geoResponse,
                    recentUsersResponse,
                ] = await loadQueryData(dateFrom, handoff, values.selectedHost)

                const bucketMap = new Map<number, SlidingWindowBucket>()

                addUserDataToBuckets(usersPageviewsResponse, bucketMap)
                addBreakdownDataToBuckets(deviceResponse, bucketMap, (b) => b.devices)
                addBreakdownDataToBuckets(browserResponse, bucketMap, (b) => b.browsers)
                addPathDataToBuckets(pathsResponse, bucketMap)
                addReferrerDataToBuckets(referrerResponse, bucketMap)
                addGeoDataToBuckets(geoResponse, bucketMap)

                actions.setInitialData(
                    [...bucketMap.entries()].map(([timestamp, bucket]) => ({ timestamp, bucket })),
                    recentUsersResponse ? getRecentUsersByLastSeenEntries(recentUsersResponse) : []
                )
            } catch (error) {
                console.error('Failed to load initial live pageview data:', error)
                lemonToast.error('Failed to load initial data')
            } finally {
                actions.setIsLoading(false)
                cache.hasInitialized = true
            }
        },
        updateConnection: () => {
            cache.eventsConnection?.abort()

            const token = values.currentTeam?.live_events_token
            if (!token) {
                return
            }

            const host = liveEventsHostOrigin()
            if (!host) {
                return
            }

            const url = new URL(`${host}/events`)
            url.searchParams.append(
                'columns',
                '$pathname,$current_url,$host,$device_type,$device_id,$browser,$ip,$raw_user_agent,$referring_domain'
            )
            if (values.selectedHost) {
                url.searchParams.append('property', `$host=${values.selectedHost}`)
            }

            cache.batch = cache.batch ?? ([] as LiveEvent[])

            cache.eventsConnection = createStreamConnection({
                url,
                token,
                onMessage: (data) => {
                    lemonToast.dismiss(ERROR_TOAST_ID)
                    cache.hasShownLiveStreamErrorToast = false

                    try {
                        const eventData = JSON.parse(data) as LiveEvent
                        cache.batch.push(eventData)
                    } catch (ex) {
                        console.error(ex)
                    }
                },
                onError: (error) => {
                    if (!cache.hasShownLiveStreamErrorToast) {
                        console.error('Live stream error:', error)
                        lemonToast.error('Live stream connection lost. Retrying...', {
                            toastId: ERROR_TOAST_ID,
                            autoClose: 5000,
                        })
                        cache.hasShownLiveStreamErrorToast = true
                    }
                },
            })
        },
        updateGeoConnection: () => {
            cache.geoConnection?.abort()

            const token = values.currentTeam?.live_events_token
            if (!token) {
                return
            }

            const host = liveEventsHostOrigin()
            if (!host) {
                return
            }

            const url = new URL(`${host}/events`)
            url.searchParams.append('geo', 'true')

            cache.geoBatch = cache.geoBatch ?? ([] as LiveGeoEvent[])

            cache.geoConnection = createStreamConnection({
                url,
                token,
                onMessage: (data) => {
                    try {
                        const geoData = JSON.parse(data) as LiveGeoEvent
                        if (geoData.countryCode && geoData.distinctId) {
                            cache.geoBatch.push(geoData)
                        }
                    } catch (ex) {
                        console.error('Failed to parse geo event:', ex)
                    }
                },
                onError: (error) => {
                    console.error('Geo stream error:', error)
                },
            })
        },
    })),
    subscriptions(({ actions, cache }) => ({
        selectedHost: () => {
            if (!cache.hasInitialized) {
                return
            }
            cache.batch = []
            cache.geoBatch = []
            actions.clearRecentEvents()
            actions.clearFilteredLiveUsers()
            actions.loadInitialData()
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.batch = [] as LiveEvent[]
            cache.geoBatch = [] as LiveGeoEvent[]

            actions.loadInitialData()
            startFlushInterval(cache as FlushCache, actions as FlushActions)

            // Ensures that our graph continues to update and old data "falls off"
            // even if new events aren't coming in
            const scheduleNextTick = (): void => {
                const now = Date.now()
                const msUntilNextMinute = 60000 - (now % 60000)
                cache.minuteTickTimeout = setTimeout(() => {
                    actions.tickCurrentMinute()
                    scheduleNextTick()
                }, msUntilNextMinute)
            }
            scheduleNextTick()
            cache.liveUserCountInterval = setInterval(() => {
                actions.tickLiveUserCount()
            }, 5000)
        },
        beforeUnmount: () => {
            cache.eventsConnection?.abort()
            cache.geoConnection?.abort()
            stopFlushInterval(cache as FlushCache)
            if (cache.minuteTickTimeout) {
                clearTimeout(cache.minuteTickTimeout)
            }
            if (cache.liveUserCountInterval) {
                clearInterval(cache.liveUserCountInterval)
                cache.liveUserCountInterval = null
            }
        },
    })),
])

interface FlushCache {
    batch: LiveEvent[]
    geoBatch: LiveGeoEvent[]
    newerThan: Date
    flushInterval: ReturnType<typeof setInterval> | null
}

interface FlushActions {
    addEvents: (events: LiveEvent[], newerThan: Date) => void
    addGeoEvents: (events: LiveGeoEvent[]) => void
}

const stopFlushInterval = (cache: FlushCache): void => {
    if (cache.flushInterval) {
        clearInterval(cache.flushInterval)
        cache.flushInterval = null
    }
}

// Flush both event and geo batches on a fixed interval
// to cap kea dispatches at a predictable rate regardless of event volume
const startFlushInterval = (cache: FlushCache, actions: FlushActions): void => {
    if (cache.flushInterval) {
        return
    }
    cache.flushInterval = setInterval(() => {
        if (cache.batch.length > 0) {
            actions.addEvents(cache.batch, cache.newerThan)
            cache.batch = []
        }
        if (cache.geoBatch.length > 0) {
            actions.addGeoEvents(cache.geoBatch)
            cache.geoBatch = []
        }
    }, FLUSH_INTERVAL_MS)
}

const loadQueryData = async (
    dateFrom: Date,
    dateTo: Date,
    host: string | null
): Promise<
    [
        HogQLQueryResponse,
        HogQLQueryResponse,
        HogQLQueryResponse,
        TrendsQueryResponse,
        HogQLQueryResponse,
        HogQLQueryResponse,
        HogQLQueryResponse | null,
    ]
> => {
    const hostFilterClause = host ? `AND properties.$host = {host}` : ''
    const hostValues = host ? { host } : {}

    const usersPageviewsQuery: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `SELECT
                    toStartOfMinute(timestamp) AS minute_bucket,
                    arrayDistinct(groupArray(distinct_id)) AS distinct_ids,
                    countIf(event = '$pageview') AS pageviews
                FROM events
                WHERE
                    timestamp >= toDateTime({dateFrom})
                    AND timestamp <= toDateTime({dateTo})
                    ${hostFilterClause}
                GROUP BY
                    minute_bucket
                ORDER BY
                    minute_bucket ASC`,
        values: {
            dateFrom: dateFrom.toISOString(),
            dateTo: dateTo.toISOString(),
            ...hostValues,
        },
    }

    const createBreakdownQuery = (property: string, alias: string): HogQLQuery => ({
        kind: NodeKind.HogQLQuery,
        query: `SELECT
                    minute_bucket,
                    mapFromArrays(
                        groupArray(${alias}),
                        groupArray(device_ids)
                    ) AS ids_by_type
                FROM
                (
                    SELECT
                        toStartOfMinute(timestamp) AS minute_bucket,
                        ifNull(properties.${property}, 'Unknown') AS ${alias},
                        arrayDistinct(groupArray(
                            if(
                                properties.$device_id IS NULL OR properties.$device_id = '$posthog_cookieless',
                                concat(
                                    'cookieless_transform|||',
                                    ifNull(properties.$ip, ''),
                                    '|||',
                                    ifNull(properties.$raw_user_agent, '')
                                ),
                                properties.$device_id
                            )
                        )) AS device_ids
                    FROM events
                    WHERE
                        timestamp >= toDateTime({dateFrom})
                        AND timestamp <= toDateTime({dateTo})
                        ${hostFilterClause}
                    GROUP BY
                        minute_bucket,
                        ${alias}
                )
                GROUP BY
                    minute_bucket
                ORDER BY
                    minute_bucket ASC`,
        values: {
            dateFrom: dateFrom.toISOString(),
            dateTo: dateTo.toISOString(),
            ...hostValues,
        },
    })

    const deviceQuery = createBreakdownQuery('$device_type', 'device_type')
    const browserQuery = createBreakdownQuery('$browser', 'browser_type')

    const pathsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        interval: 'minute',
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
        breakdownFilter: {
            breakdown_type: 'event',
            breakdown: '$pathname',
            breakdown_limit: 10,
            breakdown_hide_other_aggregation: true,
        },
        dateRange: {
            date_from: dateFrom.toISOString(),
            date_to: dateTo.toISOString(),
        },
        ...(host
            ? {
                  properties: [
                      {
                          key: '$host',
                          value: host,
                          operator: PropertyOperator.Exact,
                          type: PropertyFilterType.Event,
                      },
                  ],
              }
            : {}),
    }

    const referrerQuery: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `SELECT
                    toStartOfMinute(timestamp) AS minute_bucket,
                    if(isNotNull(properties.$referring_domain) AND properties.$referring_domain != '', properties.$referring_domain, '$direct') AS referring_domain,
                    count() AS view_count
                FROM events
                WHERE
                    timestamp >= toDateTime({dateFrom})
                    AND timestamp <= toDateTime({dateTo})
                    AND event = '$pageview'
                    ${hostFilterClause}
                GROUP BY minute_bucket, referring_domain
                ORDER BY minute_bucket ASC`,
        values: {
            dateFrom: dateFrom.toISOString(),
            dateTo: dateTo.toISOString(),
            ...hostValues,
        },
    }

    const geoQuery: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: `SELECT
                    minute_bucket,
                    mapFromArrays(
                        groupArray(country_code),
                        groupArray(distinct_ids)
                    ) AS ids_by_country
                FROM
                (
                    SELECT
                        toStartOfMinute(timestamp) AS minute_bucket,
                        properties.$geoip_country_code AS country_code,
                        arrayDistinct(groupArray(distinct_id)) AS distinct_ids
                    FROM events
                    WHERE
                        timestamp >= toDateTime({dateFrom})
                        AND timestamp <= toDateTime({dateTo})
                        AND properties.$geoip_country_code IS NOT NULL
                        AND properties.$geoip_country_code != ''
                        ${hostFilterClause}
                    GROUP BY
                        minute_bucket,
                        country_code
                )
                GROUP BY minute_bucket
                ORDER BY minute_bucket ASC`,
        values: {
            dateFrom: dateFrom.toISOString(),
            dateTo: dateTo.toISOString(),
            ...hostValues,
        },
    }

    const recentUsersQuery: HogQLQuery | null = host
        ? {
              kind: NodeKind.HogQLQuery,
              query: `SELECT
                          distinct_id,
                          toUnixTimestamp(max(timestamp)) AS last_seen
                      FROM events
                      WHERE
                          timestamp > toDateTime({dateTo}) - INTERVAL ${FILTERED_LIVE_USER_WINDOW_SECONDS} SECOND
                          AND timestamp <= toDateTime({dateTo})
                          ${hostFilterClause}
                      GROUP BY distinct_id`,
              values: {
                  dateTo: dateTo.toISOString(),
                  ...hostValues,
              },
          }
        : null

    return await Promise.all([
        performQuery(usersPageviewsQuery),
        performQuery(deviceQuery),
        performQuery(browserQuery),
        performQuery(pathsQuery),
        performQuery(referrerQuery),
        performQuery(geoQuery),
        recentUsersQuery ? performQuery(recentUsersQuery) : Promise.resolve(null),
    ])
}

const getRecentUsersByLastSeenEntries = (response: HogQLQueryResponse): [string, number][] => {
    const results = response.results as [string, number | string][]

    return results
        .map(([distinctId, lastSeenTs]) => [distinctId, Number(lastSeenTs)] as [string, number])
        .filter(([distinctId, lastSeenTs]) => distinctId !== '' && Number.isFinite(lastSeenTs))
}

const addUserDataToBuckets = (
    usersPageviewsResponse: HogQLQueryResponse,
    bucketMap: Map<number, SlidingWindowBucket>
): void => {
    const usersResults = usersPageviewsResponse.results as [string, string[], number][]

    for (const [timestampStr, distinctIds, viewCount] of usersResults) {
        const timestamp = Date.parse(timestampStr)
        const bucket = getOrCreateBucket(bucketMap, timestamp)

        bucket.pageviews = viewCount
        bucket.uniqueUsers = new Set<string>(distinctIds)
    }
}

const transformDeviceId = (deviceId: string): string => {
    if (deviceId.startsWith(COOKIELESS_TRANSFORM_PREFIX)) {
        const [_, ip, userAgent] = deviceId.split(COOKIELESS_TRANSFORM_SEPARATOR)
        return `cookieless_${hashCodeForString((ip ?? '') + (userAgent ?? ''))}`
    }
    return deviceId
}

const addBreakdownDataToBuckets = (
    response: HogQLQueryResponse,
    bucketMap: Map<number, SlidingWindowBucket>,
    getBucketMap: (bucket: SlidingWindowBucket) => Map<string, Set<string>>
): void => {
    const results = response.results as [string, Record<string, string[]>][]

    for (const [timestampStr, idsByType] of results) {
        const timestamp = Date.parse(timestampStr)
        const bucket = getOrCreateBucket(bucketMap, timestamp)

        const map = getBucketMap(bucket)
        for (const [breakdownType, deviceIds] of Object.entries(idsByType)) {
            const ids = map.get(breakdownType) ?? new Set<string>()
            for (const id of deviceIds) {
                ids.add(transformDeviceId(id))
            }
            map.set(breakdownType, ids)
        }
    }
}

const addPathDataToBuckets = (
    pathsResponse: TrendsQueryResponse,
    bucketMap: Map<number, SlidingWindowBucket>
): void => {
    for (const result of pathsResponse.results) {
        for (let i = 0; i < result.data.length; i++) {
            const timestamp = Date.parse(result.action.days[i])
            const bucket = getOrCreateBucket(bucketMap, timestamp)

            const path = result.breakdown_value
            const currentCount = bucket.paths.get(path) ?? 0

            bucket.paths.set(path, currentCount + result.data[i])
        }
    }
}

const addReferrerDataToBuckets = (
    referrerResponse: HogQLQueryResponse,
    bucketMap: Map<number, SlidingWindowBucket>
): void => {
    const results = referrerResponse.results as [string, string, number][]

    for (const [timestampStr, referringDomain, viewCount] of results) {
        const timestamp = Date.parse(timestampStr)
        const bucket = getOrCreateBucket(bucketMap, timestamp)

        const domain = referringDomain || DIRECT_REFERRER
        bucket.referrers.set(domain, (bucket.referrers.get(domain) ?? 0) + viewCount)
    }
}

const addGeoDataToBuckets = (geoResponse: HogQLQueryResponse, bucketMap: Map<number, SlidingWindowBucket>): void => {
    const results = geoResponse.results as [string, Record<string, string[]>][]

    for (const [timestampStr, idsByCountry] of results) {
        const timestamp = Date.parse(timestampStr)
        const bucket = getOrCreateBucket(bucketMap, timestamp)

        for (const [countryCode, distinctIds] of Object.entries(idsByCountry)) {
            const countryUsers = bucket.countries.get(countryCode) ?? new Set<string>()
            for (const distinctId of distinctIds) {
                countryUsers.add(distinctId)
            }
            bucket.countries.set(countryCode, countryUsers)
        }
    }
}

const getOrCreateBucket = (map: Map<number, SlidingWindowBucket>, timestamp: number): SlidingWindowBucket => {
    if (!map.has(timestamp)) {
        map.set(timestamp, createEmptyBucket())
    }

    return map.get(timestamp)!
}

const createEmptyBucket = (): SlidingWindowBucket => {
    return {
        pageviews: 0,
        newUserCount: 0,
        returningUserCount: 0,
        devices: new Map<string, Set<string>>(),
        browsers: new Map<string, Set<string>>(),
        paths: new Map<string, number>(),
        referrers: new Map<string, number>(),
        uniqueUsers: new Set<string>(),
        countries: new Map<string, Set<string>>(),
    }
}
