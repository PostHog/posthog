import { P, match } from 'ts-pattern'

import { isPostHogProperty } from '~/taxonomy/taxonomy'

import {
    ErrorEventProperties,
    ErrorTrackingException,
    ErrorTrackingRelease,
    ErrorTrackingRuntime,
    ErrorTrackingStackFrame,
    ExceptionAttributes,
    FingerprintRecordPart,
} from './types'

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
        // posthog-server is the current java server SDK identifier; posthog-java is the
        // tombstoned legacy SDK, kept so already-ingested events still resolve.
        case 'posthog-server':
        case 'posthog-java':
        case 'analytics-java':
            return 'java'
        case 'posthog-kmp':
            return 'kotlin'
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

function nonEmptyString(value: unknown): string | undefined {
    return typeof value === 'string' && value.length > 0 ? value : undefined
}

export function getExceptionAttributes(properties: Record<string, any>): ExceptionAttributes {
    const {
        $lib: lib,
        $lib_version: libVersion,
        $browser_version: browserVersion,
        $os_version: osVersion,
        $sentry_url: sentryUrl,
        $exception_level: level,
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
    // Misbehaving SDKs can send non-string values, which would crash PropertyIcon's lowercase lookup.
    const browser = nonEmptyString(properties.$browser)
    // Mobile SDKs report the platform in $os_name and leave $os unset; web SDKs do the opposite.
    const os = nonEmptyString(properties.$os_name) ?? nonEmptyString(properties.$os)

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

export function getExceptionTypeAndValue(properties: ErrorEventProperties): {
    type?: string
    value?: string
} {
    const [exception] = Array.isArray(properties.$exception_list) ? properties.$exception_list : []
    const type = properties.$exception_types?.[0] || properties.$exception_type || exception?.type
    const value = properties.$exception_values?.[0] || properties.$exception_message || exception?.value

    return {
        type: type ? stringify(type) : undefined,
        value: value ? stringify(value) : undefined,
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
            return key === 'version' || !isPostHogProperty(key, isCloudOrDev)
        })
    )
}

export function getSessionId(properties: ErrorEventProperties): string | undefined {
    const sessionId = properties['$session_id']
    // $session_id can arrive malformed (e.g. a numeric timestamp) from misbehaving SDKs.
    // Only a non-empty string is a usable session id; anything else means "no session".
    return typeof sessionId === 'string' && sessionId.length > 0 ? sessionId : undefined
}

export function getRecordingStatus(properties: ErrorEventProperties): string | undefined {
    return properties['$recording_status'] as string | undefined
}

/**
 * Normalize Cymbal's event-level release snapshot to the release API shape used by the UI.
 * The event property uses `timestamp`, while release API responses use `created_at`.
 */
export function getExceptionRelease(properties: ErrorEventProperties): ErrorTrackingRelease | undefined {
    const release: unknown = properties['$exception_release']
    if (!release || typeof release !== 'object' || Array.isArray(release)) {
        return undefined
    }

    const candidate = release as Record<string, unknown>
    if (
        typeof candidate.id !== 'string' ||
        typeof candidate.version !== 'string' ||
        typeof candidate.timestamp !== 'string'
    ) {
        return undefined
    }

    const metadata =
        candidate.metadata && typeof candidate.metadata === 'object' && !Array.isArray(candidate.metadata)
            ? (candidate.metadata as ErrorTrackingRelease['metadata'])
            : undefined

    return {
        id: candidate.id,
        version: candidate.version,
        created_at: candidate.timestamp,
        project: typeof candidate.project === 'string' ? candidate.project : undefined,
        metadata,
    }
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

export function formatFunctionName(
    frame: Pick<ErrorTrackingStackFrame, 'module' | 'resolved_name' | 'lang' | 'mangled_name'>
): string | undefined {
    const functionName: string | undefined = frame.resolved_name ?? frame.mangled_name ?? undefined
    return match([frame.lang, frame.module, functionName])
        .with(['java', P.string, P.string], ([_, module, functionName]) => `${module}.${functionName}`)
        .with(['java', P.string, P.nullish], ([_, module]) => `${module}`)
        .otherwise(() => functionName)
}

export function getInstructionAddress(frame: Pick<ErrorTrackingStackFrame, 'junk_drawer'>): string | null {
    const address = frame.junk_drawer?.raw_frame?.instruction_addr
    if (typeof address !== 'string') {
        return null
    }
    // SDKs can send a padded or blank address, which would render as an empty frame row
    const trimmed = address.trim()
    return trimmed.length > 0 ? trimmed : null
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
    const frames = exception.stacktrace?.frames
    const hasJavaFrames = Array.isArray(frames) && frames.some((frame) => frame.lang === 'java')
    return exception.module && hasJavaFrames ? `${exception.module}.${exception.type}` : exception.type
}

export function formatExceptionDisplay(
    exception: Pick<ErrorTrackingException, 'module' | 'type' | 'stacktrace' | 'value'>
): string {
    return `${formatType(exception)}${exception.value ? `: ${exception.value}` : ''}`
}
