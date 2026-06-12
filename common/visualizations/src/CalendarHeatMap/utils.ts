import { humanFriendlyNumber } from 'lib/utils'

export interface AxisConfig {
    values: string[]
}

// Calendar heatmap utility functions
export function thresholdFontSize(width: number): number {
    // These numbers are thresholds for the table's width, if we do not update the fontSize, the table overflows horizontally
    if (width < 1007) {
        // If the width is less than 1007, we virtually hide the text and show the tooltip on hover
        return 0
    } else if (width < 1134) {
        return 9
    } else if (width < 1160) {
        return 11
    }
    return 11.5
}

export const DaysAbbreviated: AxisConfig = {
    values: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
}

export const HoursAbbreviated: AxisConfig = {
    values: Array.from({ length: 24 }, (_, i) => String(i)),
}

export enum AggregationLabel {
    All = 'All',
}

export function getDataTooltip(rowLabel: string, columnLabel: string, value: number): string {
    return `${rowLabel} - ${String(columnLabel).padStart(2, '0')}:00 - ${humanFriendlyNumber(value)}`
}

export function getColumnAggregationTooltip(
    columnAggregationLabel: string,
    columnLabel: string,
    value: number
): string {
    return `${columnAggregationLabel} - ${String(columnLabel).padStart(2, '0')}:00 - ${humanFriendlyNumber(value)}`
}

export function getRowAggregationTooltip(rowAggregationLabel: string, rowLabel: string, value: number): string {
    return `${rowAggregationLabel} - ${rowLabel} - ${humanFriendlyNumber(value)}`
}

export function getOverallAggregationTooltip(overallAggregationLabel: string, value: number): string {
    return `${overallAggregationLabel} - ${humanFriendlyNumber(value)}`
}
