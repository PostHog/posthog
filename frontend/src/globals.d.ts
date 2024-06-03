import posthog from 'posthog-js'

import { ExportedData } from '~/exporter/types'

declare global {
    interface Window {
        JS_POSTHOG_API_KEY?: string
        JS_POSTHOG_HOST?: string
        JS_POSTHOG_UI_HOST?: string
        JS_POSTHOG_SELF_CAPTURE?: boolean
        JS_CAPTURE_TIME_TO_SEE_DATA?: boolean
        JS_KEA_VERBOSE_LOGGING?: boolean
        posthog?: posthog
        ESBUILD_LOAD_SCRIPT: (name) => void
        ESBUILD_LOAD_CHUNKS: (name) => void
        ESBUILD_LOADED_CHUNKS: Set<string>
        POSTHOG_EXPORTED_DATA: ExportedData
        POSTHOG_USER_IDENTITY_WITH_FLAGS?: {
            distinctID: string
            isIdentifiedID: boolean
            featureFlags: Record<string, boolean | string>
        }
        IMPERSONATED_SESSION?: boolean
        POSTHOG_JS_UUID_VERSION?: string

        EventSourcePolyfill: typeof EventSource
    }
}

/** Copied from https://github.com/DefinitelyTyped/DefinitelyTyped/blob/aaf94a0a/types/event-source-polyfill/index.d.ts#L43 */
export declare class EventSource {
    static readonly CLOSED: number
    static readonly CONNECTING: number
    static readonly OPEN: number

    constructor(url: string, eventSourceInitDict?: EventSource.EventSourceInitDict)

    readonly CLOSED: number
    readonly CONNECTING: number
    readonly OPEN: number
    readonly url: string
    readonly readyState: number
    readonly withCredentials: boolean
    onopen: (evt: MessageEvent) => any
    onmessage: (evt: MessageEvent) => any
    onerror: (evt: MessageEvent) => any
    addEventListener(type: string, listener: (evt: MessageEvent) => void): void
    dispatchEvent(evt: Event): boolean
    removeEventListener(type: string, listener: (evt: MessageEvent) => void): void
    close(): void
}
