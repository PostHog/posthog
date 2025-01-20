import { ErrorTrackingException } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'
import { range } from 'lib/utils'

import { ErrorTrackingIssue, ErrorTrackingSparklineConfig } from '~/queries/schema'

const volumePeriods: ('customVolume' | 'volumeDay' | 'volumeMonth')[] = ['customVolume', 'volumeDay', 'volumeMonth']
const sumVolumes = (...arrays: number[][]): number[] =>
    arrays[0].map((_, i) => arrays.reduce((sum, arr) => sum + arr[i], 0))

export const mergeIssues = (
    primaryIssue: ErrorTrackingIssue,
    mergingIssues: ErrorTrackingIssue[]
): ErrorTrackingIssue => {
    const sum = (value: 'occurrences' | 'users' | 'sessions'): number => {
        return mergingIssues.reduce((sum, g) => sum + g[value], primaryIssue[value])
    }

    const [firstSeen, lastSeen] = mergingIssues.reduce(
        (res, g) => {
            const firstSeen = dayjs(g.first_seen)
            const lastSeen = dayjs(g.last_seen)
            return [res[0].isAfter(firstSeen) ? firstSeen : res[0], res[1].isBefore(lastSeen) ? lastSeen : res[1]]
        },
        [dayjs(primaryIssue.first_seen), dayjs(primaryIssue.last_seen)]
    )

    volumePeriods.forEach((period) => {
        if (primaryIssue[period]) {
            const volume = primaryIssue[period]
            const mergingVolumes = mergingIssues.map((issue) => issue[period]).filter((v) => !!v)
            primaryIssue[period] = sumVolumes(...mergingVolumes, volume)
        }
    })

    return {
        ...primaryIssue,
        occurrences: sum('occurrences'),
        sessions: sum('sessions'),
        users: sum('users'),
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

export function hasStacktrace(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList?.length > 0 && exceptionList.some((e) => !!e.stacktrace)
}

export function hasAnyInAppFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some(({ stacktrace }) => stacktrace?.frames?.some(({ in_app }) => in_app))
}

export const sparklineLabelsDay = sparklineLabels({ value: 24, interval: 'hour' })
export const sparklineLabelsMonth = sparklineLabels({ value: 31, interval: 'day' })

export function sparklineLabels({ value, interval }: ErrorTrackingSparklineConfig): string[] {
    const now = dayjs().startOf(interval)
    const dates = range(value).map((idx) => now.subtract(value - (idx + 1), interval))
    return dates.map((d) => `'${d.format('D MMM, YYYY HH:mm')} (UTC)'`)
}
