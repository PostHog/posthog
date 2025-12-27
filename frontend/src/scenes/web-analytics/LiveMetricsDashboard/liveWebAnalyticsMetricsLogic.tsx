import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
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
import { ChartDataPoint, DeviceBreakdownItem, PathItem, SlidingWindowBucket } from './LiveWebAnalyticsMetricsTypes'
import type { liveWebAnalyticsMetricsLogicType } from './liveWebAnalyticsMetricsLogicType'

const ERROR_TOAST_ID = 'live-pageviews-error'
const BUCKET_WINDOW_MINUTES = 30
const BATCH_FLUSH_INTERVAL_MS = 300
const BATCH_SIZE_THRESHOLD = 10
const INITIAL_RETRY_DELAY_MS = 1000
const MAX_RETRY_DELAY_MS = 30000

export const liveWebAnalyticsMetricsLogic = kea<liveWebAnalyticsMetricsLogicType>([
    path(['scenes', 'web-analytics', 'livePageviewsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions(() => ({
        addEvents: (events: LiveEvent[]) => ({ events }),
        setInitialData: (buckets: { timestamp: number; bucket: SlidingWindowBucket }[]) => ({ buckets }),
        setIsLoading: (loading: boolean) => ({ loading }),
        loadInitialData: true,
        updateConnection: true,
        tickCurrentMinute: true,
    })),
    reducers({
        slidingWindow: [
            new LiveMetricsSlidingWindow(BUCKET_WINDOW_MINUTES),
            {
                setInitialData: (_, { buckets }) => {
                    const window = new LiveMetricsSlidingWindow(BUCKET_WINDOW_MINUTES)
                    for (const { timestamp, bucket } of buckets) {
                        window.addDataPoint(timestamp / 1000, bucket)
                    }
                    return window
                },
                addEvents: (window, { events }) => {
                    for (const event of events) {
                        const eventTs = new Date(event.timestamp).getTime() / 1000

                        const deviceType = event.properties?.$device_type
                        window.addDataPoint(eventTs, {
                            pageviews: 1,
                            devices: new Map([[deviceType, 1]]),
                            paths: new Map([[event.properties?.$pathname, 1]]),
                            distinctId: event.distinct_id,
                        })
                    }

                    return window
                },
            },
        ],
        // This is used to force a re-render every time we add an event or a minute passes
        windowVersion: [
            0,
            {
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

                // Generate all minute buckets for the window
                const currentBucketTs = Math.floor(Date.now() / 60000) * 60
                for (let i = BUCKET_WINDOW_MINUTES - 1; i >= 0; i--) {
                    const ts = currentBucketTs - i * 60
                    const bucket = bucketMap.get(ts)

                    result.push({
                        minute: dayjs.unix(ts).format('HH:mm'),
                        timestamp: ts * 1000,
                        users: bucket?.uniqueUsers.size ?? 0,
                        pageviews: bucket?.pageviews ?? 0,
                    })
                }

                return result
            },
        ],
        deviceBreakdown: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): DeviceBreakdownItem[] => {
                const totals = slidingWindow.getDeviceTotals()

                // TODO: We should keep track of this data as we ingest events into the SlidingWindow
                //  so we don't need to iterate over a bunch of data
                let total = 0
                for (const count of totals.values()) {
                    total += count
                }

                if (total === 0) {
                    return []
                }

                return [...totals.entries()]
                    .map(([device, count]) => ({
                        device,
                        count,
                        percentage: (count / total) * 100,
                    }))
                    .sort((a, b) => b.count - a.count)
            },
        ],
        topPaths: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): PathItem[] => slidingWindow.getTopPaths(10),
        ],
        totalPageviews: [
            (s) => [s.slidingWindow, s.windowVersion],
            (slidingWindow: LiveMetricsSlidingWindow): number => slidingWindow.getTotalPageviews(),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        loadInitialData: async () => {
            actions.setIsLoading(true)

            try {
                const [usersPageviewsResponse, deviceResponse, pathsResponse] = await loadQueryData()

                const bucketMap = new Map<number, SlidingWindowBucket>()

                addUserDataToBuckets(usersPageviewsResponse, bucketMap)
                addDeviceDataToBuckets(deviceResponse, bucketMap)
                addPathDataToBuckets(pathsResponse, bucketMap)

                actions.setInitialData([...bucketMap.entries()].map(([timestamp, bucket]) => ({ timestamp, bucket })))

                // Start listening to the SSE connection
                actions.updateConnection()
            } catch (error) {
                console.error('Failed to load initial live pageview data:', error)
                lemonToast.error('Failed to load initial data')
            } finally {
                actions.setIsLoading(false)
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
            url.searchParams.append('eventType', '$pageview')

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

            api.stream(url.toString(), {
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
                        actions.addEvents(cache.batch)
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

const loadQueryData = async (): Promise<[HogQLQueryResponse, TrendsQueryResponse, TrendsQueryResponse]> => {
    const cutoff = new Date(Date.now() - 30 * 60 * 1000).toISOString()

    const usersPageviewsQuery: HogQLQuery = {
        kind: NodeKind.HogQLQuery,
        query: "SELECT toStartOfMinute(timestamp) AS minute_bucket, arrayDistinct(groupArray(distinct_id)) AS distinct_users, count() as total FROM events WHERE event = '$pageview' AND timestamp >= now() - INTERVAL 30 MINUTE GROUP BY minute_bucket ORDER BY minute_bucket ASC",
    }

    const deviceQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        interval: 'minute',
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
        breakdownFilter: { breakdown_type: 'event', breakdown: '$device_type' },
        dateRange: { date_from: cutoff },
    }

    const pathsQuery: TrendsQuery = {
        kind: NodeKind.TrendsQuery,
        interval: 'minute',
        series: [{ kind: NodeKind.EventsNode, event: '$pageview', math: BaseMathType.TotalCount }],
        breakdownFilter: { breakdown_type: 'event', breakdown: '$pathname', breakdown_limit: 10 },
        dateRange: { date_from: cutoff },
    }

    return await Promise.all([performQuery(usersPageviewsQuery), performQuery(deviceQuery), performQuery(pathsQuery)])
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

const addDeviceDataToBuckets = (
    deviceResponse: TrendsQueryResponse,
    bucketMap: Map<number, SlidingWindowBucket>
): void => {
    for (const result of deviceResponse.results) {
        const deviceType = result.breakdown_value || 'Unknown'

        for (let i = 0; i < result.data.length; i++) {
            const timestamp = Date.parse(result.action.days[i])
            const bucket = getOrCreateBucket(bucketMap, timestamp)

            const currentDeviceCount = bucket.devices.get(deviceType) ?? 0

            bucket.devices.set(deviceType, currentDeviceCount + (result.data[i] || 0))
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
        devices: new Map<string, number>(),
        paths: new Map<string, number>(),
        uniqueUsers: new Set<string>(),
    }
}
