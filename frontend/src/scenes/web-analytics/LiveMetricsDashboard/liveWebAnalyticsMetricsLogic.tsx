import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { hashCodeForString } from 'lib/utils'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { performQuery } from '~/queries/query'
import {
    HogQLQuery,
    HogQLQueryResponse,
    NodeKind,
    TrendsQuery,
    TrendsQueryResponse,
} from '~/queries/schema/schema-general'
import { BaseMathType, LiveEvent } from '~/types'

import { LiveMetricsSlidingWindow } from './LiveMetricsSlidingWindow'
import {
    BrowserBreakdownItem,
    ChartDataPoint,
    DeviceBreakdownItem,
    PathItem,
    SlidingWindowBucket,
} from './LiveWebAnalyticsMetricsTypes'
import type { liveWebAnalyticsMetricsLogicType } from './liveWebAnalyticsMetricsLogicType'

const ERROR_TOAST_ID = 'live-pageviews-error'
const RECONNECT_TOAST_ID = 'live-pageviews-reconnect'
const BUCKET_WINDOW_MINUTES = 30
const BATCH_FLUSH_INTERVAL_MS = 300
const BATCH_SIZE_THRESHOLD = 10
const INITIAL_RETRY_DELAY_MS = 1000
const MAX_RETRY_DELAY_MS = 30000
const COOKIELESS_TRANSFORM_PREFIX = 'cookieless_transform'
const COOKIELESS_TRANSFORM_SEPARATOR = '|||'

export const liveWebAnalyticsMetricsLogic = kea<liveWebAnalyticsMetricsLogicType>([
    path(['scenes', 'web-analytics', 'livePageviewsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions(() => ({
        addEvents: (events: LiveEvent[], newerThan: Date) => ({ events, newerThan }),
        setInitialData: (buckets: { timestamp: number; bucket: SlidingWindowBucket }[]) => ({ buckets }),
        setIsLoading: (loading: boolean) => ({ loading }),
        loadInitialData: true,
        updateConnection: true,
        tickCurrentMinute: true,
        pauseStream: true,
        resumeStream: true,
    })),
    reducers({
        slidingWindow: [
            new LiveMetricsSlidingWindow(BUCKET_WINDOW_MINUTES),
            {
                setInitialData: (existingWindow, { buckets }) => {
                    for (const { timestamp, bucket } of buckets) {
                        existingWindow.extendBucketData(timestamp / 1000, bucket)
                    }
                    return existingWindow
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

                            // For cookieless events, device_id isn't set before preprocessing
                            // so we create a device key from IP + user agent
                            let deviceKey = deviceId
                            if (!deviceKey || deviceKey === '$posthog_cookieless') {
                                const ip = event.properties?.$ip ?? ''
                                const ua = event.properties?.$raw_user_agent ?? ''
                                deviceKey = `cookieless_${hashCodeForString(ip + ua)}`
                            }

                            window.addDataPoint(eventTs, event.distinct_id, {
                                pageviews: event.event === '$pageview' ? 1 : 0,
                                device: deviceType ? { deviceId: deviceKey, deviceType } : undefined,
                                browser: browser ? { deviceId: deviceKey, browserType: browser } : undefined,
                                pathname: event.event === '$pageview' ? pathname : undefined,
                            })
                        }
                    }

                    return window
                },
            },
        ],
        // This is used to force a re-render every time we add an event or a minute passes
        windowVersion: [
            0,
            {
                setInitialData: (v) => v + 1,
                addEvents: (v) => v + 1,
                tickCurrentMinute: (v) => v + 1,
            },
        ],
        isLoading: [
            true,
            {
                setIsLoading: (_, { loading }) => loading,
            },
        ],
    }),
    selectors({
        chartData: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): ChartDataPoint[] => {
                const bucketMap = new Map(slidingWindow.getSortedBuckets())
                const result: ChartDataPoint[] = []
                const seenUsers = new Set<string>()

                const currentBucketTs = Math.floor(Date.now() / 60000) * 60
                for (let i = BUCKET_WINDOW_MINUTES - 1; i >= 0; i--) {
                    const ts = currentBucketTs - i * 60
                    const bucket = bucketMap.get(ts)

                    let newUsers = 0
                    let returningUsers = 0

                    if (bucket) {
                        for (const userId of bucket.uniqueUsers) {
                            if (seenUsers.has(userId)) {
                                returningUsers++
                            } else {
                                newUsers++
                                seenUsers.add(userId)
                            }
                        }
                    }

                    result.push({
                        minute: dayjs.unix(ts).format('HH:mm'),
                        timestamp: ts * 1000,
                        users: bucket?.uniqueUsers.size ?? 0,
                        newUsers,
                        returningUsers,
                        pageviews: bucket?.pageviews ?? 0,
                    })
                }

                return result
            },
        ],
        deviceBreakdown: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): DeviceBreakdownItem[] => slidingWindow.getDeviceBreakdown(),
        ],
        browserBreakdown: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): BrowserBreakdownItem[] => slidingWindow.getBrowserBreakdown(6),
        ],
        topPaths: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): PathItem[] => slidingWindow.getTopPaths(10),
        ],
        totalPageviews: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalPageviews(),
        ],
        totalUniqueVisitors: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalUniqueUsers(),
        ],
        totalBrowsers: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalBrowsers(),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        pauseStream: () => {
            cache.eventSourceController?.abort()
            if (cache.retryTimeout) {
                clearTimeout(cache.retryTimeout)
                cache.retryTimeout = null
            }
        },
        resumeStream: () => {
            if (cache.hasInitialized) {
                lemonToast.info('Refreshing live data...', {
                    toastId: RECONNECT_TOAST_ID,
                    autoClose: 2000,
                })
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
                const [usersPageviewsResponse, deviceResponse, browserResponse, pathsResponse] = await loadQueryData(
                    dateFrom,
                    handoff
                )

                const bucketMap = new Map<number, SlidingWindowBucket>()

                addUserDataToBuckets(usersPageviewsResponse, bucketMap)
                addBreakdownDataToBuckets(deviceResponse, bucketMap, (b) => b.devices)
                addBreakdownDataToBuckets(browserResponse, bucketMap, (b) => b.browsers)
                addPathDataToBuckets(pathsResponse, bucketMap)

                actions.setInitialData([...bucketMap.entries()].map(([timestamp, bucket]) => ({ timestamp, bucket })))
            } catch (error) {
                console.error('Failed to load initial live pageview data:', error)
                lemonToast.error('Failed to load initial data')
            } finally {
                actions.setIsLoading(false)
                cache.hasInitialized = true
            }
        },
        updateConnection: async () => {
            cache.eventSourceController?.abort()
            if (cache.retryTimeout) {
                clearTimeout(cache.retryTimeout)
                cache.retryTimeout = null
            }

            if (!values.currentTeam) {
                return
            }

            const host = liveEventsHostOrigin()
            if (!host) {
                return
            }

            const url = new URL(`${host}/events`)
            url.searchParams.append('columns', '$pathname,$device_type,$device_id,$browser,$ip,$raw_user_agent')

            cache.batch = [] as LiveEvent[]
            cache.lastBatchTime = performance.now()
            cache.eventSourceController = new AbortController()

            const scheduleRetry = (): void => {
                const currentDelay = cache.retryDelay ?? INITIAL_RETRY_DELAY_MS
                cache.retryTimeout = setTimeout(() => {
                    actions.updateConnection()
                }, currentDelay)

                cache.retryDelay = Math.min(currentDelay * 2, MAX_RETRY_DELAY_MS)
            }

            await api.stream(url.toString(), {
                headers: {
                    Authorization: `Bearer ${values.currentTeam.live_events_token}`,
                },
                signal: cache.eventSourceController.signal,
                onMessage: (event) => {
                    lemonToast.dismiss(ERROR_TOAST_ID)
                    cache.hasShownLiveStreamErrorToast = false
                    cache.retryDelay = INITIAL_RETRY_DELAY_MS

                    try {
                        const eventData = JSON.parse(event.data) as LiveEvent
                        cache.batch.push(eventData)
                    } catch (ex) {
                        console.error(ex)
                    }

                    // Flush events when we have enough or enough time has passed
                    const timeSinceLastBatch = performance.now() - cache.lastBatchTime
                    if (cache.batch.length >= BATCH_SIZE_THRESHOLD || timeSinceLastBatch > BATCH_FLUSH_INTERVAL_MS) {
                        actions.addEvents(cache.batch, cache.newerThan)
                        cache.batch = []
                        cache.lastBatchTime = performance.now()
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
                    scheduleRetry()
                },
            })
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadInitialData()

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
        },
        beforeUnmount: () => {
            cache.eventSourceController?.abort()
            if (cache.minuteTickTimeout) {
                clearTimeout(cache.minuteTickTimeout)
            }
            if (cache.retryTimeout) {
                clearTimeout(cache.retryTimeout)
            }
        },
    })),
])

const loadQueryData = async (
    dateFrom: Date,
    dateTo: Date
): Promise<[HogQLQueryResponse, HogQLQueryResponse, HogQLQueryResponse, TrendsQueryResponse]> => {
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
                GROUP BY
                    minute_bucket
                ORDER BY
                    minute_bucket ASC`,
        values: {
            dateFrom: dateFrom.toISOString(),
            dateTo: dateTo.toISOString(),
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
    }

    return await Promise.all([
        performQuery(usersPageviewsQuery),
        performQuery(deviceQuery),
        performQuery(browserQuery),
        performQuery(pathsQuery),
    ])
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

const getOrCreateBucket = (map: Map<number, SlidingWindowBucket>, timestamp: number): SlidingWindowBucket => {
    if (!map.has(timestamp)) {
        map.set(timestamp, createEmptyBucket())
    }

    return map.get(timestamp)!
}

const createEmptyBucket = (): SlidingWindowBucket => {
    return {
        pageviews: 0,
        devices: new Map<string, Set<string>>(),
        browsers: new Map<string, Set<string>>(),
        paths: new Map<string, number>(),
        uniqueUsers: new Set<string>(),
    }
}
