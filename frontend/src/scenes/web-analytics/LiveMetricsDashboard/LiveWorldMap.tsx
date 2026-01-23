import './LiveWorldMap.scss'

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { getSeriesColor } from 'lib/colors'
import { gradateColor } from 'lib/utils'
import { COUNTRY_CODE_TO_LONG_NAME, countryCodeToFlag } from 'lib/utils/geography/country'
import { countryVectors } from 'scenes/insights/views/WorldMap/countryVectors'

import { CountryBreakdownItem } from './LiveWebAnalyticsMetricsTypes'

const SATURATION_FLOOR = 0.2
const TOOLTIP_OFFSET_PX = 12
const HEAT_DECAY_MS = 3000
const HEAT_UPDATE_INTERVAL_MS = 100

interface TooltipData {
    countryCode: string
    countryName: string
    flag: string
    count: number
    percentage: number
    x: number
    y: number
}

interface LiveWorldMapProps {
    data: CountryBreakdownItem[]
    totalEvents: number
}

export const LiveWorldMap = ({ data, totalEvents }: LiveWorldMapProps): JSX.Element => {
    const [hoveredCountry, setHoveredCountry] = useState<{ code: string; x: number; y: number } | null>(null)
    const [countryHeat, setCountryHeat] = useState<Record<string, number>>({})
    const prevCountsRef = useRef<Record<string, number>>({})
    const lastActivityRef = useRef<Record<string, number>>({})

    // Use the same color as the main analytics map (preset-1)
    const mapColor = useMemo(() => getSeriesColor(0), [])

    const countryCodeToCount = useMemo(() => {
        const map: Record<string, number> = {}
        for (const item of data) {
            if (item.country) {
                map[item.country] = item.count
            }
        }
        return map
    }, [data])

    // Track when countries receive new activity
    useEffect(() => {
        const now = Date.now()
        for (const [countryCode, count] of Object.entries(countryCodeToCount)) {
            const prevCount = prevCountsRef.current[countryCode] || 0
            if (count > prevCount) {
                lastActivityRef.current[countryCode] = now
            }
        }
        prevCountsRef.current = { ...countryCodeToCount }
    }, [countryCodeToCount])

    // Decay heat over time
    useEffect(() => {
        const interval = setInterval(() => {
            const now = Date.now()
            const newHeat: Record<string, number> = {}

            for (const [countryCode, lastActivity] of Object.entries(lastActivityRef.current)) {
                const elapsed = now - lastActivity
                const heat = Math.max(0, 1 - elapsed / HEAT_DECAY_MS)
                if (heat > 0) {
                    newHeat[countryCode] = heat
                }
            }

            setCountryHeat(newHeat)
        }, HEAT_UPDATE_INTERVAL_MS)

        return () => clearInterval(interval)
    }, [])

    const maxCount = useMemo(() => {
        return Math.max(...data.map((d) => d.count), 1)
    }, [data])

    const handleMouseEnter = useCallback((countryCode: string, e: React.MouseEvent) => {
        setHoveredCountry({ code: countryCode, x: e.clientX, y: e.clientY })
    }, [])

    const handleMouseMove = useCallback((e: React.MouseEvent) => {
        setHoveredCountry((prev) => (prev ? { ...prev, x: e.clientX, y: e.clientY } : null))
    }, [])

    const handleMouseLeave = useCallback(() => {
        setHoveredCountry(null)
    }, [])

    // Compute tooltip data from current state so it updates live
    const tooltip = useMemo((): TooltipData | null => {
        if (!hoveredCountry) {
            return null
        }
        const count = countryCodeToCount[hoveredCountry.code] || 0
        if (count === 0) {
            return null
        }
        return {
            countryCode: hoveredCountry.code,
            countryName: COUNTRY_CODE_TO_LONG_NAME[hoveredCountry.code] || hoveredCountry.code,
            flag: countryCodeToFlag(hoveredCountry.code),
            count,
            percentage: totalEvents > 0 ? (count / totalEvents) * 100 : 0,
            x: hoveredCountry.x,
            y: hoveredCountry.y,
        }
    }, [hoveredCountry, countryCodeToCount, totalEvents])

    const hasData = data.some((d) => d.count > 0)

    if (!hasData) {
        return (
            <div className="h-full flex items-center justify-center text-muted text-sm">No country data available</div>
        )
    }

    return (
        <div className="LiveWorldMap relative h-full w-full">
            <svg
                className="LiveWorldMap__svg"
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
                            filter: heat > 0 ? `brightness(${1 + heat * 0.8}) saturate(${1 + heat * 0.5})` : undefined,
                            transition: 'filter 0.15s ease-out',
                        },
                        onMouseEnter: (e: React.MouseEvent) => handleMouseEnter(countryCode, e),
                        onMouseMove: handleMouseMove,
                        onMouseLeave: handleMouseLeave,
                    })
                })}
            </svg>
            {tooltip && (
                <div
                    className="LiveWorldMap__tooltip"
                    style={{
                        left: tooltip.x + TOOLTIP_OFFSET_PX,
                        top: tooltip.y + TOOLTIP_OFFSET_PX,
                    }}
                >
                    <div className="LiveWorldMap__tooltip-content">
                        <div className="LiveWorldMap__tooltip-country">
                            <span className="LiveWorldMap__tooltip-flag">{tooltip.flag}</span>
                            <span>{tooltip.countryName}</span>
                        </div>
                        <span className="LiveWorldMap__tooltip-count">{tooltip.count.toLocaleString()}</span>
                    </div>
                    <div className="LiveWorldMap__tooltip-footer">{tooltip.percentage.toFixed(1)}% of traffic</div>
                </div>
            )}
        </div>
    )
}
