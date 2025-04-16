export interface AxisConfig {
    values: string[]
    startIndex?: number
}

export interface AggregationConfig {
    label: string
    fn: (values: number[]) => number
}

export const Sum: AggregationConfig = {
    label: 'Sum',
    fn: (values) => values.reduce((acc, val) => acc + val, 0),
}

export const DaysAbbreviated: AxisConfig = {
    values: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    startIndex: 0,
}

export const HoursAbbreviated: AxisConfig = {
    values: Array.from({ length: 24 }, (_, i) => String(i)),
    startIndex: 0,
}
