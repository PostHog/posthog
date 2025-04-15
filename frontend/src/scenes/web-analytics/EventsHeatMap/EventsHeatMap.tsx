import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useValues } from 'kea'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ActiveHoursHeatMapQuery, ActiveHoursHeatMapResult } from '~/queries/schema/schema-general'
import { HeatMapCell } from './HeatMapCell'
import { DaysAbbreviated, HoursAbbreviated, Sum, COLORS } from './config'
import './EventsHeatMap.scss'
import { QueryContext } from '~/queries/types'

interface EventsHeatMapProps {
    query: ActiveHoursHeatMapQuery
    context: QueryContext
}

export function EventsHeatMap({ query, context }: EventsHeatMapProps): JSX.Element {
    const containerRef = useRef<HTMLDivElement>(null)
    const [fontSize, setFontSize] = useState(13)
    const [showTooltip, setShowTooltip] = useState(false)

    const updateSize = useCallback(() => {
        if (!containerRef.current) return
        const width = containerRef.current.offsetWidth
        if (width < 954) {
            setFontSize(0)
            setShowTooltip(true)
        } else {
            setFontSize(Math.min(13, Math.floor(width / 80)))
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
                style={{ '--heatmap-table-color': COLORS.heatmap } as React.CSSProperties}
            >
                <tbody>
                    {/* Header row */}
                    <tr>
                        <th className="bg" />
                        {yAggregations[0] !== undefined && <th>{Sum.label}</th>}
                        {HoursAbbreviated.values.map((label, i) => (
                            <th key={i}>{label}</th>
                        ))}
                    </tr>

                    {/* Aggregation row */}
                    <tr>
                        {xAggregations[0] !== undefined && <td className="EventsHeatMap__TextTab">{Sum.label}</td>}
                        {renderOverallCell(overallValue, showTooltip, fontSize)}
                        {renderAggregationCells(xAggregations, maxXAggregation, showTooltip, fontSize)}
                    </tr>

                    {/* Data rows */}
                    {rotatedYLabels.map((day, yIndex) => (
                        <tr key={yIndex}>
                            <td className="EventsHeatMap__TextTab">{day}</td>
                            {renderYAggregationCell(yAggregations[yIndex], maxYAggregation, day, showTooltip, fontSize)}
                            {renderDataCells(matrix[yIndex], maxValue, day, showTooltip, fontSize)}
                        </tr>
                    ))}
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

function renderOverallCell(overallValue: number, showTooltip: boolean, fontSize: number) {
    return overallValue !== undefined ? (
        <td>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={overallValue}
                maxValue={1}
                backgroundColor="#000000"
                dayAndTime={Sum.label}
            />
        </td>
    ) : <td />
}

function renderAggregationCells(xAggregations: { [key: number]: number }, maxXAggregation: number, showTooltip: boolean, fontSize: number) {
    return xAggregations[0] !== undefined && Array.from({ length: HoursAbbreviated.values.length }, (_, x) => (
        <td key={x}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={xAggregations[x]}
                maxValue={maxXAggregation}
                backgroundColor={COLORS.aggregation}
                dayAndTime={`${Sum.label} - ${String(x).padStart(2, '0')}:00`}
            />
        </td>
    ))
}

function renderYAggregationCell(value: number, maxYAggregation: number, day: string, showTooltip: boolean, fontSize: number) {
    return Sum && value !== undefined && (
        <td>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={value}
                maxValue={maxYAggregation}
                backgroundColor={COLORS.aggregation}
                dayAndTime={`${Sum.label} - ${day}`}
            />
        </td>
    )
}

function renderDataCells(rowData: { [key: number]: number }, maxValue: number, day: string, showTooltip: boolean, fontSize: number) {
    return Array.from({ length: HoursAbbreviated.values.length }, (_, x) => (
        <td key={x}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={rowData[x]}
                maxValue={maxValue}
                backgroundColor={COLORS.heatmap}
                dayAndTime={`${day} - ${String(x).padStart(2, '0')}:00`}
            />
        </td>
    ))
}
