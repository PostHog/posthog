import { ErrorTrackingException } from 'lib/components/Errors/types'
import { dayjs } from 'lib/dayjs'

import { ErrorTrackingIssue } from '~/queries/schema'

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

    const volume = primaryIssue.volume

    if (volume) {
        const dataIndex = 3
        const data = mergingIssues.reduce(
            (sum: number[], g) => g.volume[dataIndex].map((num: number, idx: number) => num + sum[idx]),
            primaryIssue.volume[dataIndex]
        )
        volume.splice(dataIndex, 1, data)
    }

    return {
        ...primaryIssue,
        occurrences: sum('occurrences'),
        sessions: sum('sessions'),
        users: sum('users'),
        first_seen: firstSeen.toISOString(),
        last_seen: lastSeen.toISOString(),
        volume: volume,
    }
}

export function getExceptionProperties(
    properties: Record<string, any>
): { ingestionErrors?: string[]; exceptionList: ErrorTrackingException[] } & Record<
    | 'type'
    | 'value'
    | '$exception_synthetic'
    | '$lib'
    | '$lib_version'
    | '$browser'
    | '$browser_version'
    | '$os'
    | '$os_version'
    | '$sentry_url'
    | 'level',
    any
> {
    const {
        $lib,
        $lib_version,
        $browser,
        $browser_version,
        $os,
        $os_version,
        $sentry_url,
        $sentry_exception,
        $level: level,
        $cymbal_errors: ingestionErrors,
    } = properties

    let type = properties.$exception_type
    let value = properties.$exception_message
    let $exception_synthetic = properties.$exception_synthetic
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
    if ($exception_synthetic == undefined) {
        $exception_synthetic = exceptionList?.[0]?.mechanism?.synthetic
    }

    return {
        type,
        value,
        $exception_synthetic,
        $lib,
        $lib_version,
        $browser,
        $browser_version,
        $os,
        $os_version,
        $sentry_url,
        exceptionList: exceptionList || [],
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
