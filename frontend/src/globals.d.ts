import posthog from 'posthog-js'
import { ExportedData } from '~/exporter/types'

declare global {
    interface Window {
        JS_POSTHOG_API_KEY?: str
        JS_POSTHOG_HOST?: str
        JS_POSTHOG_SELF_CAPTURE?: boolean
        JS_CAPTURE_INTERNAL_METRICS?: boolean
        JS_CAPTURE_TIME_TO_SEE_DATA?: boolean
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
    }
}
