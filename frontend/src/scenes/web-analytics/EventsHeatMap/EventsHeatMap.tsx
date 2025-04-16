import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ActiveHoursHeatMapQuery, ActiveHoursHeatMapResult } from '~/queries/schema/schema-general'
import { HeatMapCell } from './HeatMapCell'
import { DaysAbbreviated, HoursAbbreviated, Sum } from './config'
import './EventsHeatMap.scss'
import { QueryContext } from '~/queries/types'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

interface EventsHeatMapProps {
    query: ActiveHoursHeatMapQuery
    context: QueryContext
}

export function EventsHeatMap({ query, context }: EventsHeatMapProps): JSX.Element {
    const { themes, getTheme } = useValues(dataThemeLogic)
    const theme = getTheme(themes?.[0]?.id)

    const heatmapColor = theme?.['preset-1'] ?? '#000000' // Default to black if no color found
    const aggregationColor = theme?.['preset-2'] ?? '#000000' // Default to black if no color found
    const backgroundColorOverall = theme?.['preset-3'] || '#000000' // Default to black if no color found
    const containerRef = useRef<HTMLDivElement>(null)
    const [fontSize, setFontSize] = useState(13)
    const [showTooltip, setShowTooltip] = useState(false)

    const updateSize = useCallback(() => {
        if (!containerRef.current) return
        const width = containerRef.current.offsetWidth
        console.log("width", width)
        if (width < 1007) {
            setFontSize(0)
            setShowTooltip(true)
        } else if (width < 1134) {
            setFontSize(9)
            setShowTooltip(false)
        } else if (width < 1160) {
            setFontSize(11)
            setShowTooltip(false)
        } else {
            setFontSize(11.5)
            setShowTooltip(false)
        }
    }, [])

    useEffect(() => {
        const element = containerRef.current
        if (!element) return

        updateSize()
        const resizeObserver = new ResizeObserver(updateSize)
        resizeObserver.observe(element)
        return () => resizeObserver.unobserve(element)
    }, [updateSize])

    const { response } = useValues(dataNodeLogic({ query, key: 'events-heat-map', dataNodeCollectionId: context.insightProps?.dataNodeCollectionId }))

    const { matrix, maxValue, xAggregations, yAggregations, maxXAggregation, maxYAggregation, overallValue } = 
        processData(response?.results ?? [])

    const rotatedYLabels = [
        ...DaysAbbreviated.values.slice(DaysAbbreviated.startIndex || 0),
        ...DaysAbbreviated.values.slice(0, DaysAbbreviated.startIndex || 0)
    ]

    return (
        <div className="EventsHeatMapContainer" ref={containerRef}>
            <table 
                className="EventsHeatMap"
                style={{ '--heatmap-table-color': heatmapColor } as React.CSSProperties}
            >
                <tbody>
                    {/* Header row */}
                    <tr>
                        <th className="bg" />
                        {HoursAbbreviated.values.map((label, i) => (
                            <th key={i}>{label}</th>
                        ))}
                        {yAggregations[0] !== undefined && <th style={{borderLeft: '5px solid transparent'}}>{Sum.label}</th>}
                    </tr>

                    {/* Data rows */}
                    {rotatedYLabels.map((day, yIndex) => (
                        <tr key={yIndex}>
                            <td className="EventsHeatMap__TextTab">{day}</td>
                            {renderDataCells(matrix[yIndex], maxValue, day, showTooltip, fontSize, heatmapColor)}
                            {renderYAggregationCell(yAggregations[yIndex], maxYAggregation, day, showTooltip, fontSize, aggregationColor)}
                        </tr>
                    ))}

                    {/* Aggregation row */}
                    <tr style={{borderTop: '5px solid transparent'}}>
                        {xAggregations[0] !== undefined && <td className="EventsHeatMap__TextTab">{Sum.label}</td>}
                        {renderAggregationCells(xAggregations, maxXAggregation, showTooltip, fontSize, aggregationColor)}
                        {renderOverallCell(overallValue, showTooltip, fontSize, backgroundColorOverall)}
                    </tr>
                </tbody>
            </table>
        </div>
    )
}

function processData(results: ActiveHoursHeatMapResult[]) {
    const matrix: { [key: number]: { [key: number]: number } } = {}
    let maxValue = 0
    let maxXAggregation = 0
    let maxYAggregation = 0

    // Initialize matrix
    for (let i = 0; i < DaysAbbreviated.values.length; i++) {
        matrix[i] = {}
        for (let x = 0; x < HoursAbbreviated.values.length; x++) {
            matrix[i][x] = 0
        }
    }

    // Fill matrix
    results.forEach((result) => {
        const adjustedDay = (result.day - (DaysAbbreviated.startIndex || 0) + DaysAbbreviated.values.length) % DaysAbbreviated.values.length
        matrix[adjustedDay][result.hour] = result.total
        maxValue = Math.max(maxValue, result.total)
    })

    // Calculate aggregations
    const xAggregations = calculateXAggregations(matrix)
    const yAggregations = calculateYAggregations(matrix)
    maxXAggregation = Math.max(...Object.values(xAggregations))
    maxYAggregation = Math.max(...Object.values(yAggregations))

    const allValues = Object.values(matrix).flatMap(row => Object.values(row))
    const overallValue = Sum.fn(allValues)

    return { matrix, maxValue, xAggregations, yAggregations, maxXAggregation, maxYAggregation, overallValue }
}

function calculateXAggregations(matrix: { [key: number]: { [key: number]: number } }) {
    const xAggregations: { [key: number]: number } = {}
    for (let x = 0; x < HoursAbbreviated.values.length; x++) {
        const values = Object.values(matrix).map(day => day[x])
        xAggregations[x] = Sum.fn(values)
    }
    return xAggregations
}

function calculateYAggregations(matrix: { [key: number]: { [key: number]: number } }) {
    const yAggregations: { [key: number]: number } = {}
    for (let y = 0; y < DaysAbbreviated.values.length; y++) {
        yAggregations[y] = Sum.fn(Object.values(matrix[y]))
    }
    return yAggregations
}

function renderOverallCell(overallValue: number, showTooltip: boolean, fontSize: number, backgroundColorOverall: string) {
    return overallValue !== undefined ? (
        <td style={{borderLeft: '5px solid transparent'}}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={overallValue}
                maxValue={1}
                backgroundColor={backgroundColorOverall}
                    dayAndTime={Sum.label}
                    />
        </td>
    ) : <td />
}

function renderAggregationCells(xAggregations: { [key: number]: number }, maxXAggregation: number, showTooltip: boolean, fontSize: number, aggregationColor: string) {
    return xAggregations[0] !== undefined && Array.from({ length: HoursAbbreviated.values.length }, (_, x) => (
        <td key={x}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={xAggregations[x]}
                maxValue={maxXAggregation}
                backgroundColor={aggregationColor}
                dayAndTime={`${Sum.label} - ${String(x).padStart(2, '0')}:00`}
                />
        </td>
    ))
}

function renderYAggregationCell(value: number, maxYAggregation: number, day: string, showTooltip: boolean, fontSize: number, aggregationColor: string) {
    return Sum && value !== undefined && (
        <td style={{borderLeft: '5px solid transparent'}}>
                <HeatMapCell
                    showTooltip={showTooltip}
                    fontSize={fontSize}
                    value={value}
                    maxValue={maxYAggregation}
                    backgroundColor={aggregationColor}
                    dayAndTime={`${Sum.label} - ${day}`}
                />
        </td>
    )
}

function renderDataCells(rowData: { [key: number]: number }, maxValue: number, day: string, showTooltip: boolean, fontSize: number, heatmapColor: string) {
    return Array.from({ length: HoursAbbreviated.values.length }, (_, x) => (
        <td key={x}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={rowData[x]}
                maxValue={maxValue}
                backgroundColor={heatmapColor}
                dayAndTime={`${day} - ${String(x).padStart(2, '0')}:00`}
            />
        </td>
    ))
}
