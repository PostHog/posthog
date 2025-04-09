import { ErrorTrackingException } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { componentsToDayJs, dateStringToComponents, isStringDateRegex, objectsEqual } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { DateRange, ErrorTrackingIssue } from '~/queries/schema/schema-general'

import { DEFAULT_ERROR_TRACKING_DATE_RANGE, DEFAULT_ERROR_TRACKING_FILTER_GROUP } from './errorTrackingLogic'

export const ERROR_TRACKING_LOGIC_KEY = 'errorTracking'
const THIRD_PARTY_SCRIPT_ERROR = 'Script error.'

export const SEARCHABLE_EXCEPTION_PROPERTIES = [
    '$exception_types',
    '$exception_values',
    '$exception_sources',
    '$exception_functions',
]

const volumePeriods: ('volumeRange' | 'volumeDay')[] = ['volumeRange', 'volumeDay']
const sumVolumes = (...arrays: number[][]): number[] =>
    arrays[0].map((_, i) => arrays.reduce((sum, arr) => sum + arr[i], 0))

export const mergeIssues = (
    primaryIssue: ErrorTrackingIssue,
    mergingIssues: ErrorTrackingIssue[]
): ErrorTrackingIssue => {
    const [firstSeen, lastSeen] = mergingIssues.reduce(
        (res, g) => {
            const firstSeen = dayjs(g.first_seen)
            const lastSeen = dayjs(g.last_seen)
            return [res[0].isAfter(firstSeen) ? firstSeen : res[0], res[1].isBefore(lastSeen) ? lastSeen : res[1]]
        },
        [dayjs(primaryIssue.first_seen), dayjs(primaryIssue.last_seen)]
    )

    const aggregations = primaryIssue.aggregations

    if (aggregations) {
        const sum = (value: 'occurrences' | 'users' | 'sessions'): number => {
            return mergingIssues.reduce((sum, g) => sum + (g.aggregations?.[value] || 0), aggregations[value])
        }

        volumePeriods.forEach((period) => {
            const volume = aggregations[period]
            if (volume) {
                const mergingVolumes = mergingIssues.map((issue) => issue.aggregations?.[period]).filter((v) => !!v)
                aggregations[period] = sumVolumes(...mergingVolumes, volume)
            }
        })

        aggregations.users = sum('users')
        aggregations.sessions = sum('sessions')
        aggregations.occurrences = sum('occurrences')
    }

    return {
        ...primaryIssue,
        aggregations,
        first_seen: firstSeen.toISOString(),
        last_seen: lastSeen.toISOString(),
    }
}

export function getExceptionAttributes(
    properties: Record<string, any>
): { ingestionErrors?: string[]; exceptionList: ErrorTrackingException[] } & Record<
    'type' | 'value' | 'synthetic' | 'library' | 'browser' | 'os' | 'sentryUrl' | 'level' | 'unhandled',
    any
> {
    const {
        $lib,
        $lib_version,
        $browser: browser,
        $browser_version: browserVersion,
        $os: os,
        $os_version: osVersion,
        $sentry_url: sentryUrl,
        $sentry_exception,
        $level: level,
        $cymbal_errors: ingestionErrors,
    } = properties

    let type = properties.$exception_type
    let value = properties.$exception_message
    let synthetic: boolean | undefined = properties.$exception_synthetic
    let exceptionList: ErrorTrackingException[] | undefined = properties.$exception_list

    // exception autocapture sets $exception_list for all exceptions.
    // If it's not present, then this is probably a sentry exception. Get this list from the sentry_exception
    if (!exceptionList?.length && $sentry_exception) {
        if (Array.isArray($sentry_exception.values)) {
            exceptionList = $sentry_exception.values
        }
    }

    if (!type) {
        type = exceptionList?.[0]?.type
    }
    if (!value) {
        value = exceptionList?.[0]?.value
    }
    if (synthetic == undefined) {
        synthetic = exceptionList?.[0]?.mechanism?.synthetic
    }

    const handled = exceptionList?.[0]?.mechanism?.handled ?? false

    return {
        type,
        value,
        synthetic,
        library: `${$lib} ${$lib_version}`,
        browser: browser ? `${browser} ${browserVersion}` : undefined,
        os: os ? `${os} ${osVersion}` : undefined,
        sentryUrl,
        exceptionList: exceptionList || [],
        unhandled: !handled,
        level,
        ingestionErrors,
    }
}

export function getSessionId(properties: Record<string, any>): string | undefined {
    return properties['$session_id']
}

export function hasStacktrace(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList?.length > 0 && exceptionList.some((e) => !!e.stacktrace)
}

export function isThirdPartyScriptError(value: ErrorTrackingException['value']): boolean {
    return value === THIRD_PARTY_SCRIPT_ERROR
}

export function hasAnyInAppFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some(({ stacktrace }) => stacktrace?.frames?.some(({ in_app }) => in_app))
}

export function generateSparklineLabels(range: DateRange, resolution: number): string[] {
    const resolvedDateRange = resolveDateRange(range)
    const from = dayjs(resolvedDateRange.date_from)
    const to = dayjs(resolvedDateRange.date_to)
    const labels = Array.from({ length: resolution }, (_, i) => {
        const bin_size = Math.floor(to.diff(from, 'seconds') / resolution)
        return from.add(i * bin_size, 'seconds').toISOString()
    })
    return labels
}

export class ResolvedDateRange {
    date_from: Dayjs
    date_to: Dayjs

    constructor(date_from: Dayjs, date_to: Dayjs) {
        this.date_from = date_from
        this.date_to = date_to
    }

    toDateRange(): DateRange {
        return {
            date_from: this.date_from.toISOString(),
            date_to: this.date_to.toISOString(),
        }
    }

    static fromDateRange(dateRange: DateRange): ResolvedDateRange {
        return new ResolvedDateRange(resolveDate(dateRange.date_from), resolveDate(dateRange.date_to))
    }
}

// Converts relative date range to absolute date range
export function resolveDateRange(dateRange: DateRange): ResolvedDateRange {
    return ResolvedDateRange.fromDateRange(dateRange)
}

// Converts relative date to absolute date.
export function resolveDate(date?: string | null): Dayjs {
    if (!date) {
        return dayjs()
    }
    if (date == 'all') {
        return dayjs().subtract(1, 'year')
    }
    const parsedDate = datetimeStringToDayJs(date)
    if (parsedDate) {
        return parsedDate
    }
    throw new Error(`Invalid date: ${date}`)
}

const customOptions: Record<string, string> = {
    dStart: 'Today', // today
    mStart: 'Month',
    yStart: 'Year',
    all: 'All',
}

export function generateDateRangeLabel(dateRange: DateRange): string | undefined {
    const dateFrom = dateRange.date_from
    if (!dateFrom) {
        return undefined
    }
    const isDateRelative = isStringDateRegex.test(dateFrom)
    if (dateFrom in customOptions) {
        return customOptions[dateFrom]
    } else if (isDateRelative) {
        return dateFrom?.replace('-', '')
    }
    return 'Custom'
}

export function datetimeStringToDayJs(date: string | null): Dayjs | null {
    if (!isStringDateRegex.test(date || '')) {
        return dayjs(date)
    }
    const dateComponents = dateStringToComponents(date)
    if (!dateComponents) {
        return dayjs()
    }
    return componentsToDayJs(dateComponents)
}

export function defaultSearchParams({ searchQuery, filterGroup, filterTestAccounts, dateRange }: any): Params {
    const searchParams: Params = {
        filterTestAccounts,
    }

    if (searchQuery) {
        searchParams.searchQuery = searchQuery
    }
    if (!objectsEqual(filterGroup, DEFAULT_ERROR_TRACKING_FILTER_GROUP)) {
        searchParams.filterGroup = filterGroup
    }
    if (!objectsEqual(dateRange, DEFAULT_ERROR_TRACKING_DATE_RANGE)) {
        searchParams.dateRange = dateRange
    }

    return searchParams
}
