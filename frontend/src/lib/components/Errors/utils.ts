import { ErrorTrackingException, ErrorTrackingRuntime } from './types'

export function hasStacktrace(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList?.length > 0 && exceptionList.some((e) => !!e.stacktrace)
}

export function hasInAppFrames(exceptionList: ErrorTrackingException[]): boolean {
    return exceptionList.some(({ stacktrace }) => stacktraceHasInAppFrames(stacktrace))
}

export function stacktraceHasInAppFrames(stacktrace: ErrorTrackingException['stacktrace']): boolean {
    return stacktrace?.frames?.some(({ in_app }) => in_app) ?? false
}

export function getRuntimeFromLib(lib: string): ErrorTrackingRuntime {
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
