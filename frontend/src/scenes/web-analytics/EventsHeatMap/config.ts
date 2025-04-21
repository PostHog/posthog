export enum AggregationLabel {
    All = 'All',
}
export interface AxisConfig {
    values: string[]
    startIndex?: number
}

export interface AggregationConfig {
    label: string
    fn: (values: number[]) => number
}

export const DaysAbbreviated: AxisConfig = {
    values: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    startIndex: 0,
}

export const HoursAbbreviated: AxisConfig = {
    values: Array.from({ length: 24 }, (_, i) => String(i)),
    startIndex: 0,
}
