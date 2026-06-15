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

/**
 * True for benign client-side network failures that are outside PostHog's control —
 * ad-blockers, CORS mismatches, offline/transient drops. `fetch` rejects with a
 * TypeError ("Failed to fetch") for these, and `AbortSignal.timeout` rejects with an
 * AbortError DOMException. The toolbar swallows and recovers from these, so they should
 * not open error-tracking issues — reserve `captureToolbarException` for genuine defects.
 */
export function isClientNetworkError(error: unknown): boolean {
    if (error instanceof TypeError) {
        return true
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
        return true
    }
    return false
}

/** Capture an exception with a required toolbar context tag for filtering. */
export function captureToolbarException(
    error: unknown,
    context: string,
    additionalProperties?: Record<string, unknown>
): void {
    toolbarPosthogJS.captureException(error, {
        toolbar_context: context,
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
