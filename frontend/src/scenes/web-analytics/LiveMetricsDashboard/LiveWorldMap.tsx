import 'scenes/insights/views/WorldMap/WorldMap.scss'

import { useActions, useValues } from 'kea'
import React, { useEffect } from 'react'

import { gradateColor } from 'lib/utils'
import { countryVectors } from 'scenes/insights/views/WorldMap/countryVectors'

import { CountryBreakdownItem } from './LiveWebAnalyticsMetricsTypes'
import { liveWorldMapLogic } from './liveWorldMapLogic'

const SATURATION_FLOOR = 0.3
const HEAT_BRIGHTNESS_FACTOR = 0.8
const HEAT_HUE_ROTATION_DEG = 180
const HEAT_TRANSITION_DURATION = '0.15s'

interface LiveWorldMapProps {
    data: CountryBreakdownItem[]
    totalEvents: number
}

export const LiveWorldMap = ({ data, totalEvents }: LiveWorldMapProps): JSX.Element => {
    const { countryCodeToCount, maxCount, tooltipData, countryHeat, mapColor, tooltipPosition } =
        useValues(liveWorldMapLogic)
    const { showTooltip, hideTooltip, updateTooltipCoordinates, updateCountryData } = useActions(liveWorldMapLogic)

    useEffect(() => {
        updateCountryData(data, totalEvents)
    }, [data, totalEvents, updateCountryData])

    const handleMouseEnter = (countryCode: string, e: React.MouseEvent): void => {
        showTooltip(countryCode)
        updateTooltipCoordinates(e.clientX, e.clientY)
    }

    const handleMouseMove = (e: React.MouseEvent): void => {
        updateTooltipCoordinates(e.clientX, e.clientY)
    }

    const handleMouseLeave = (): void => {
        hideTooltip()
    }

    return (
        <div className="relative">
            <svg
                className="WorldMap max-w-4xl mx-auto"
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 2754 1200"
                width="100%"
                height="100%"
            >
                {Object.entries(countryVectors).map(([countryCode, countryElement]) => {
                    if (countryCode.length !== 2) {
                        return null
                    }
                    const count = countryCodeToCount[countryCode] || 0
                    const fill = count > 0 ? gradateColor(mapColor, count / maxCount, SATURATION_FLOOR) : undefined
                    const heat = countryHeat[countryCode] || 0

                    return React.cloneElement(countryElement, {
                        key: countryCode,
                        style: {
                            color: fill,
                            '--world-map-hover': mapColor,
                            cursor: count > 0 ? 'pointer' : undefined,
                            filter:
                                heat > 0
                                    ? `brightness(${1 + heat * HEAT_BRIGHTNESS_FACTOR}) saturate(${1 + heat}) hue-rotate(${heat * HEAT_HUE_ROTATION_DEG}deg)`
                                    : undefined,
                            transition: `filter ${HEAT_TRANSITION_DURATION} ease-out`,
                        },
                        onMouseEnter: (e: React.MouseEvent) => handleMouseEnter(countryCode, e),
                        onMouseMove: handleMouseMove,
                        onMouseLeave: handleMouseLeave,
                    })
                })}
            </svg>
            {tooltipData && tooltipPosition && (
                <div
                    className="fixed z-[var(--z-graph-tooltip)] pointer-events-none bg-bg-light border border-border rounded-lg shadow-lg overflow-hidden"
                    style={{
                        left: tooltipPosition.left,
                        top: tooltipPosition.top,
                    }}
                >
                    <div className="flex items-center justify-between px-3 py-2 border-b border-border">
                        <div className="flex gap-2 items-center font-semibold">
                            <span className="text-lg">{tooltipData.flag}</span>
                            <span className="text-sm">{tooltipData.countryName}</span>
                        </div>
                        <span className="font-semibold text-sm tabular-nums ml-4">
                            {tooltipData.count.toLocaleString()}
                        </span>
                    </div>
                    <div className="px-3 py-2 text-xs text-secondary">
                        {tooltipData.percentage.toFixed(1)}% of traffic
                    </div>
                </div>
            )}
        </div>
    )
}
