import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { FeatureFlagKey } from 'lib/constants'

const DEFAULT_API_KEY = 'sTMFPsFhdP1Ssg'

const runningOnPosthog = !!window.POSTHOG_APP_CONTEXT
const apiKey = runningOnPosthog ? window.JS_POSTHOG_API_KEY : DEFAULT_API_KEY
const apiHost = runningOnPosthog ? window.JS_POSTHOG_HOST : 'https://internal-j.posthog.com'

const initResult = posthog.init(
    apiKey || DEFAULT_API_KEY,
    {
        api_host: apiHost,
        opt_out_capturing_by_default: true, // must call .opt_in_capturing() before any events are sent
        persistence: 'memory', // We don't want to persist anything, all events are in-memory
        persistence_name: apiKey + '_toolbar', // We don't need this but it ensures we don't accidentally mess with the standard persistence
        bootstrap: {
            featureFlags: {},
        },
        autocapture: false,
        capture_pageview: false,
        capture_pageleave: false,
        disable_surveys: true,
        disable_scroll_properties: true,
        disable_product_tours: true,
        disable_session_recording: true,
        session_recording: {
            // we want to capture the toolbar (which is marked with ph-no-capture
            // so customer sessions don't see it), but also respect the customer's
            // ph-no-capture marks
            blockClass: 'ph-internal-no-capture',
            blockSelector: '.ph-no-capture:not(#__POSTHOG_TOOLBAR__):not(#__POSTHOG_TOOLBAR__ *)',
            maskAllInputs: true,
        },
    },
    'ph_toolbar_internal'
)
if (!initResult) {
    throw new Error('Failed to initialize PostHog toolbar instance')
}
export const toolbarPosthogJS = initResult

if (runningOnPosthog && window.JS_POSTHOG_SELF_CAPTURE) {
    toolbarPosthogJS.debug()
}

export type ToolbarFetchErrorType = 'timeout' | 'network_or_cors' | 'http_error' | 'unknown'

/** Classify a fetch-style error so it can be tagged on captured events. */
export function classifyFetchError(error: unknown): ToolbarFetchErrorType {
    if (error instanceof DOMException && error.name === 'AbortError') {
        return 'timeout'
    }
    if (error instanceof TypeError) {
        return 'network_or_cors'
    }
    if (error instanceof Error && error.message.startsWith('HTTP ')) {
        return 'http_error'
    }
    return 'unknown'
}

/** Capture an exception with a required toolbar context tag for filtering.
 *
 * Safari uses a generic `TypeError: Load failed` for every fetch failure (CORS
 * rejection, network drop, abort), which collapses unrelated toolbar errors
 * into one fingerprint in error tracking. To avoid that noise:
 *  - We rewrap opaque fetch failures with a stable, context-specific message
 *    so each `toolbar_context` fingerprints independently.
 *  - For `ui_host_check` we skip the duplicate `$exception` entirely — that
 *    code path already emits a structured `toolbar ui host check` event with
 *    `status: 'error'`, and the reachability check is a UX helper, not a
 *    security boundary, so the extra exception adds no signal.
 */
export function captureToolbarException(
    error: unknown,
    context: string,
    additionalProperties?: Record<string, unknown>
): void {
    const fetchErrorType = classifyFetchError(error)
    const isOpaqueFetchFailure = fetchErrorType === 'network_or_cors' || fetchErrorType === 'timeout'

    if (isOpaqueFetchFailure && context === 'ui_host_check') {
        return
    }

    let captured: unknown = error
    const extra: Record<string, unknown> = { toolbar_context: context }

    if (fetchErrorType !== 'unknown') {
        extra.error_type = fetchErrorType
    }

    if (isOpaqueFetchFailure && error instanceof Error) {
        extra.original_error_message = error.message
        const wrapped = new Error(`toolbar fetch failed (${fetchErrorType}) [${context}]`)
        wrapped.name = error.name
        wrapped.stack = error.stack
        captured = wrapped
    }

    toolbarPosthogJS.captureException(captured, {
        ...extra,
        ...additionalProperties,
    })
}

export const useToolbarFeatureFlag = (flag: FeatureFlagKey, match?: string): boolean => {
    const [flagValue, setFlagValue] = useState<boolean | string | undefined>(toolbarPosthogJS.getFeatureFlag(flag))

    useEffect(() => {
        return toolbarPosthogJS.onFeatureFlags(() => setFlagValue(toolbarPosthogJS.getFeatureFlag(flag)))
    }, [flag, match])

    if (match) {
        return flagValue === match
    }

    return !!flagValue
}
