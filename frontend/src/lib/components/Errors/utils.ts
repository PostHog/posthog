import { isPostHogProperty } from '~/taxonomy/taxonomy'

import {
    ErrorEventProperties,
    ErrorTrackingException,
    ErrorTrackingRuntime,
    ErrorTrackingStackFrame,
    ExceptionAttributes,
    FingerprintRecordPart,
} from './types'

export function hasStacktrace(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.length > 0 && exceptionList.some((e) => !!e.stacktrace)
}

export function hasInAppFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some(({ stacktrace }) => stacktraceHasInAppFrames(stacktrace))
}

export function stacktraceHasInAppFrames(stacktrace: ErrorTrackingException['stacktrace']): boolean {
    return stacktrace?.frames?.some(({ in_app }) => in_app) ?? false
}

export function getRuntimeFromLib(lib?: string | null): ErrorTrackingRuntime {
    switch (lib?.toLowerCase()) {
        case 'posthog-python':
            return 'python'
        case 'posthog-node':
        case 'analytics-node':
        case 'posthog-edge':
            return 'node'
        case 'posthog-js':
        case 'web':
        case 'js':
            return 'web'
        case 'posthog-go':
        case 'analytics-go':
            return 'go'
        case 'posthog-php':
            return 'php'
        case 'posthog-rs':
            return 'rust'
        case 'posthog-dotnet':
            return 'dotnet'
        case 'posthog-android':
            return 'android'
        case 'posthog-ios':
        case 'ios-widget':
            return 'ios'
        case 'posthog-react-native':
            return 'react-native'
        case 'posthog-dart':
            return 'dart'
        case 'posthog-flutter':
            return 'flutter'
        case 'posthog-elixir':
            return 'elixir'
        case 'posthog-java':
        case 'analytics-java':
            return 'java'
        default:
            return 'unknown'
    }
}

export function concatValues(
    attrs: ExceptionAttributes | null,
    ...keys: (keyof ExceptionAttributes)[]
): string | undefined {
    if (!attrs) {
        return undefined
    }
    const definedKeys = keys.filter((key) => attrs[key])
    if (definedKeys.length == 0) {
        return undefined
    }
    return definedKeys.map((key) => attrs[key]).join(' ')
}

export function getExceptionAttributes(properties: Record<string, any>): ExceptionAttributes {
    const {
        $lib: lib,
        $lib_version: libVersion,
        $browser: browser,
        $browser_version: browserVersion,
        $os: os,
        $os_version: osVersion,
        $sentry_url: sentryUrl,
        $level: level,
        $cymbal_errors: ingestionErrors,
    } = properties

    let type = properties.$exception_type
    let value = properties.$exception_message
    let synthetic: boolean | undefined = properties.$exception_synthetic
    const url: string | undefined = properties.$current_url
    const exceptionList: ErrorTrackingException[] | undefined = getExceptionList(properties)
    if (!type) {
        // we have seen in production that we managed to get `value = {}`
        // so even though this is typed as a string
        // it might not be!
        type = exceptionList?.[0]?.type ? stringify(exceptionList?.[0]?.type) : undefined
    }
    if (!value) {
        // we have seen in production that we managed to get `value = {}`
        // so even though this is typed as a string
        // it might not be!
        value = exceptionList?.[0]?.value ? stringify(exceptionList?.[0]?.value) : undefined
    }
    if (synthetic == undefined) {
        synthetic = exceptionList?.[0]?.mechanism?.synthetic
    }

    const handled = exceptionList?.[0]?.mechanism?.handled ?? false
    const runtime: ErrorTrackingRuntime = getRuntimeFromLib(lib)
    const appNamespace = properties.$app_namespace
    const appVersion = properties.$app_version

    return {
        type,
        value,
        synthetic,
        runtime,
        lib,
        libVersion,
        browser,
        browserVersion,
        os,
        osVersion,
        url,
        sentryUrl,
        handled,
        level,
        ingestionErrors,
        appNamespace,
        appVersion,
    }
}

export function getExceptionList(properties: ErrorEventProperties): ErrorTrackingException[] {
    const { $sentry_exception } = properties

    let exceptionList: ErrorTrackingException[] = processExceptionList(properties.$exception_list)

    // exception autocapture sets $exception_list for all exceptions.
    // If it's not present, then this is probably a sentry exception. Get this list from the sentry_exception
    if (!exceptionList?.length && $sentry_exception) {
        if (Array.isArray($sentry_exception.values)) {
            exceptionList = $sentry_exception.values
        }
    }

    return exceptionList
}

function processExceptionList(exceptionList: ErrorTrackingException[] = []): ErrorTrackingException[] {
    exceptionList = ensureStringExceptionValues(exceptionList)
    exceptionList = ensureFrameIdFormat(exceptionList)
    return exceptionList
}

function ensureFrameIdFormat(exceptionList: ErrorTrackingException[]): ErrorTrackingException[] {
    exceptionList = exceptionList.map((exception) => {
        if (!exception.stacktrace || !exception.stacktrace.frames || !Array.isArray(exception.stacktrace.frames)) {
            return exception
        }
        exception.stacktrace.frames = exception.stacktrace.frames.map((frame) => {
            frame.raw_id = frame.raw_id ? coerceLegacyRawId(frame.raw_id) : frame.raw_id
            return frame
        })
        return exception
    })
    return exceptionList
}

function coerceLegacyRawId(rawId: string): string {
    return rawId.includes('/') ? rawId : `${rawId}/0`
}

export function getFingerprintRecords(properties: ErrorEventProperties): FingerprintRecordPart[] {
    const { $exception_fingerprint_record } = properties
    return $exception_fingerprint_record || []
}

export function getAdditionalProperties(
    properties: ErrorEventProperties,
    isCloudOrDev: boolean | undefined
): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(properties).filter(([key]) => {
            return !isPostHogProperty(key, isCloudOrDev)
        })
    )
}

export function getSessionId(properties: ErrorEventProperties): string | undefined {
    return properties['$session_id'] as string | undefined
}

export function getRecordingStatus(properties: ErrorEventProperties): string | undefined {
    return properties['$recording_status'] as string | undefined
}

// we had a bug where SDK was sending non-string values for exception value
function ensureStringExceptionValues(exceptionList: ErrorTrackingException[]): ErrorTrackingException[] {
    if (!Array.isArray(exceptionList)) {
        return []
    }

    return exceptionList.map((exception) => ({
        ...exception,
        value: stringify(exception.value),
    }))
}

export function stringify(value: any): string {
    if (typeof value === 'string') {
        return value
    }

    try {
        return JSON.stringify(value)
    } catch {}

    try {
        return value.toString()
    } catch {}

    return ''
}

export function formatResolvedName(
    frame: Pick<ErrorTrackingStackFrame, 'module' | 'resolved_name' | 'lang'>
): string | null {
    if (!frame.resolved_name || frame.resolved_name === '?') {
        return null
    }
    return frame.module && frame.lang === 'java' ? `${frame.module}.${frame.resolved_name}` : frame.resolved_name
}

export function formatType(exception: Pick<ErrorTrackingException, 'module' | 'type' | 'stacktrace'>): string {
    const hasJavaFrames = exception.stacktrace?.frames?.some((frame) => frame.lang === 'java')

    return exception.module && hasJavaFrames ? `${exception.module}.${exception.type}` : exception.type
}
