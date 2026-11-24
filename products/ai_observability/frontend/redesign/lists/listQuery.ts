import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { dateStringToDayJs } from 'lib/utils/dateFilters'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

// ponytail: the lists read HogQL from the client while the screens settle. Each read moves to a server resource with a
// generated client before it ships, so an API caller gets the same answers.

export interface ListScope {
    propertyFilters: AnyPropertyFilter[]
    filterTestAccounts: boolean
    dateFrom: string
    dateTo: string | null
}

export interface VolumeBuckets {
    startEpoch: number
    seconds: number
    count: number
    labels: string[]
}

const HOUR = 3600
const DAY = 24 * HOUR

export function volumeBuckets(dateFrom: string, dateTo: string | null): VolumeBuckets {
    const end = (dateTo ? dateStringToDayJs(dateTo) : null) ?? dayjs()
    const start = dateStringToDayJs(dateFrom) ?? end.subtract(7, 'day')
    const range = Math.max(end.unix() - start.unix(), HOUR)
    const seconds = range <= 2 * DAY ? HOUR : range <= 90 * DAY ? DAY : 7 * DAY
    const count = Math.ceil(range / seconds)
    const format = seconds === HOUR ? 'MMM D, HH:mm' : 'MMM D'
    return {
        startEpoch: start.unix(),
        seconds,
        count,
        labels: Array.from({ length: count }, (_, index) => start.add(index * seconds, 'second').format(format)),
    }
}

/** A HogQL expression for an event's bucket index, read back by `volumeSeries`. */
export function bucketExpr(buckets: VolumeBuckets): string {
    return `toInt64(intDiv(toUnixTimestamp(timestamp) - ${buckets.startEpoch}, ${buckets.seconds}))`
}

/** Turns a `sumMap([bucket], [n])` value into one count per bucket. */
export function volumeSeries(buckets: VolumeBuckets, value: unknown): number[] {
    const series = new Array<number>(buckets.count).fill(0)
    const [keys, counts] = Array.isArray(value) ? (value as [number[], number[]]) : [[], []]
    keys.forEach((key, index) => {
        series[Math.min(Math.max(Number(key), 0), buckets.count - 1)] += Number(counts[index]) || 0
    })
    return series
}

export async function hogqlRows<T>(
    query: string,
    scope: ListScope,
    values: Record<string, unknown> = {}
): Promise<T[]> {
    const response = await api.query({
        kind: NodeKind.HogQLQuery,
        query,
        values,
        filters: {
            properties: scope.propertyFilters,
            filterTestAccounts: scope.filterTestAccounts,
            dateRange: { date_from: scope.dateFrom, date_to: scope.dateTo },
        },
    } as HogQLQuery)
    const columns: string[] = response.columns ?? []
    return (response.results ?? []).map(
        (row: unknown[]) => Object.fromEntries(columns.map((column, index) => [column, row[index]])) as T
    )
}
