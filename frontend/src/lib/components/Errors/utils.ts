import { ExceptionAttributes } from 'scenes/error-tracking/utils'

import { ErrorTrackingException, ErrorTrackingRuntime } from './types'

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
    switch (lib) {
        case 'posthog-python':
            return 'python'
        case 'posthog-node':
            return 'node'
        case 'posthog-js':
        case 'web':
            return 'web'
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
