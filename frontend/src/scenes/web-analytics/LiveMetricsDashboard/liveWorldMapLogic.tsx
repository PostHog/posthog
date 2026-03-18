import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import { getSeriesColor } from 'lib/colors'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'

import { CountryBreakdownItem } from './LiveWebAnalyticsMetricsTypes'
import type { liveWorldMapLogicType } from './liveWorldMapLogicType'

const HEAT_DECAY_MS = 3000
const HEAT_UPDATE_INTERVAL_MS = 250
const TOOLTIP_OFFSET_PX = 12
const TOOLTIP_WIDTH_ESTIMATE = 200
const TOOLTIP_HEIGHT_ESTIMATE = 80

export interface TooltipData {
    countryCode: string
    countryName: string
    flag: string
    count: number
    percentage: number
    x: number
    y: number
}

export const liveWorldMapLogic = kea<liveWorldMapLogicType>([
    path(['scenes', 'web-analytics', 'LiveMetricsDashboard', 'liveWorldMapLogic']),
    actions({
        showTooltip: (countryCode: string) => ({ countryCode }),
        hideTooltip: true,
        updateTooltipCoordinates: (x: number, y: number) => ({ x, y }),
        updateCountryData: (data: CountryBreakdownItem[], totalEvents: number) => ({ data, totalEvents }),
        setCountryHeat: (heat: Record<string, number>) => ({ heat }),
    }),
    reducers({
        hoveredCountryCode: [
            null as string | null,
            {
                showTooltip: (_, { countryCode }) => countryCode,
                hideTooltip: () => null,
            },
        ],
        tooltipCoordinates: [
            null as { x: number; y: number } | null,
            {
                updateTooltipCoordinates: (_, { x, y }) => ({ x, y }),
                hideTooltip: () => null,
            },
        ],
        countryData: [
            [] as CountryBreakdownItem[],
            {
                updateCountryData: (_, { data }) => data,
            },
        ],
        totalEvents: [
            0,
            {
                updateCountryData: (_, { totalEvents }) => totalEvents,
            },
        ],
        countryHeat: [
            {} as Record<string, number>,
            {
                setCountryHeat: (_, { heat }) => heat,
            },
        ],
    }),
    selectors({
        countryCodeToCount: [
            (s) => [s.countryData],
            (data: CountryBreakdownItem[]): Record<string, number> => {
                const map: Record<string, number> = {}
                for (const item of data) {
                    if (item.country) {
                        map[item.country] = item.count
                    }
                }
                return map
            },
        ],
        maxCount: [
            (s) => [s.countryData],
            (data: CountryBreakdownItem[]): number => {
                return Math.max(...data.map((d) => d.count), 1)
            },
        ],
        hasData: [
            (s) => [s.countryData],
            (data: CountryBreakdownItem[]): boolean => {
                return data.some((d) => d.count > 0)
            },
        ],
        tooltipData: [
            (s) => [s.hoveredCountryCode, s.tooltipCoordinates, s.countryCodeToCount, s.totalEvents],
            (
                hoveredCountryCode: string | null,
                coords: { x: number; y: number } | null,
                countryCodeToCount: Record<string, number>,
                totalEvents: number
            ): TooltipData | null => {
                if (!hoveredCountryCode || !coords) {
                    return null
                }
                const count = countryCodeToCount[hoveredCountryCode] || 0
                if (count === 0) {
                    return null
                }
                return {
                    countryCode: hoveredCountryCode,
                    countryName: COUNTRY_CODE_TO_LONG_NAME[hoveredCountryCode] || hoveredCountryCode,
                    flag: countryCodeToFlag(hoveredCountryCode),
                    count,
                    percentage: totalEvents > 0 ? (count / totalEvents) * 100 : 0,
                    x: coords.x,
                    y: coords.y,
                }
            },
        ],
        mapColor: [() => [], (): string => getSeriesColor(0)],
        tooltipPosition: [
            (s) => [s.tooltipData],
            (tooltipData: TooltipData | null): { left: number; top: number } | null => {
                if (!tooltipData) {
                    return null
                }
                const { x, y } = tooltipData
                const viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 0
                const viewportHeight = typeof window !== 'undefined' ? window.innerHeight : 0

                const wouldOverflowRight = x + TOOLTIP_OFFSET_PX + TOOLTIP_WIDTH_ESTIMATE > viewportWidth
                const wouldOverflowBottom = y + TOOLTIP_OFFSET_PX + TOOLTIP_HEIGHT_ESTIMATE > viewportHeight

                return {
                    left: wouldOverflowRight ? x - TOOLTIP_OFFSET_PX - TOOLTIP_WIDTH_ESTIMATE : x + TOOLTIP_OFFSET_PX,
                    top: wouldOverflowBottom ? y - TOOLTIP_OFFSET_PX - TOOLTIP_HEIGHT_ESTIMATE : y + TOOLTIP_OFFSET_PX,
                }
            },
        ],
    }),
    listeners(({ actions, cache }) => ({
        updateCountryData: ({ data }) => {
            const now = Date.now()
            const prevCounts = cache.prevCounts || {}
            const lastActivity = cache.lastActivity || {}

            // Skip heat updates on initial load
            const isInitialLoad = !cache.initialized
            cache.initialized = true

            if (!isInitialLoad) {
                for (const item of data) {
                    if (item.country) {
                        const prevCount = prevCounts[item.country] || 0
                        if (item.count > prevCount) {
                            lastActivity[item.country] = now
                        }
                    }
                }
            }

            cache.lastActivity = lastActivity
            cache.prevCounts = Object.fromEntries(data.map((item: CountryBreakdownItem) => [item.country, item.count]))

            actions.setCountryHeat(computeHeat(lastActivity))
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.prevCounts = {}
            cache.lastActivity = {}

            cache.heatInterval = setInterval(() => {
                const heat = computeHeat(cache.lastActivity || {})
                actions.setCountryHeat(heat)
            }, HEAT_UPDATE_INTERVAL_MS)
        },
        beforeUnmount: () => {
            if (cache.heatInterval) {
                clearInterval(cache.heatInterval)
            }
        },
    })),
])

function computeHeat(lastActivity: Record<string, number>): Record<string, number> {
    const now = Date.now()
    const heat: Record<string, number> = {}

    for (const [countryCode, lastActivityTime] of Object.entries(lastActivity)) {
        const elapsed = now - lastActivityTime
        const heatValue = Math.max(0, 1 - elapsed / HEAT_DECAY_MS)
        if (heatValue > 0) {
            heat[countryCode] = heatValue
        }
    }

    return heat
}
