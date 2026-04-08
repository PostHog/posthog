import posthog from 'posthog-js'

import { ExportedData } from '~/exporter/types'

declare global {
    // Monaco Editor environment configuration
    // See: https://github.com/microsoft/monaco-editor/blob/main/docs/integrate-esm.md
    interface MonacoEnvironment {
        getWorker?(moduleId: string, label: string): Worker
        getWorkerUrl?(moduleId: string, label: string): string
    }

    // eslint-disable-next-line no-var
    var MonacoEnvironment: MonacoEnvironment | undefined

    // Build-time constant injected by esbuild's `define` (see
    // frontend/toolbar-config.mjs). Empty string in posthog/posthog's own
    // builds; set to e.g. `https://us-assets.i.posthog.com/static/1.358.0/`
    // when the toolbar is built by posthog-js's release workflow as part of a
    // self-contained, version-pinned bundle. Used by the toolbar to load
    // sibling files (currently just toolbar.css) from the same versioned URL.
    const __POSTHOG_TOOLBAR_PUBLIC_PATH__: string

    interface Window {
        JS_URL?: string
        JS_POSTHOG_API_KEY?: string
        JS_POSTHOG_HOST?: string
        JS_POSTHOG_UI_HOST?: string
        JS_POSTHOG_SELF_CAPTURE?: boolean
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
        IMPERSONATED_SESSION?: boolean
        POSTHOG_JS_UUID_VERSION?: string

        // These are used to track global errors across the app.
        // Can be used to determine whether we should show warnings in different places in the app.
        POSTHOG_GLOBAL_ERRORS?: Record<string, boolean>
    }
}
