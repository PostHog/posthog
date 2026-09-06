import posthog, { CaptureResult } from 'posthog-js'
import { useEffect, useState } from 'react'

import { FeatureFlagKey } from 'lib/constants'

const DEFAULT_API_KEY = 'sTMFPsFhdP1Ssg'

const runningOnPosthog = !!window.POSTHOG_APP_CONTEXT
const apiKey = runningOnPosthog ? window.JS_POSTHOG_API_KEY : DEFAULT_API_KEY
const apiHost = runningOnPosthog ? window.JS_POSTHOG_HOST : 'https://internal-j.posthog.com'

// Events posthog-js collects about the page it runs on. For the toolbar that page belongs to a
// customer, so our internal project must not receive any of them.
const HOST_PAGE_CAPTURE_EVENTS = new Set([
    '$autocapture',
    '$copy_autocapture',
    '$dead_click',
    '$pageleave',
    '$pageview',
    '$rageclick',
    '$web_vitals',
    '$$heatmap',
])

// The init options below fall back to remote config when unset, so the internal project's settings
// could switch host page capture back on. This drops the events whatever the server says.
function dropHostPageCapture(event: CaptureResult | null): CaptureResult | null {
    if (!event) {
        return event
    }
    if (HOST_PAGE_CAPTURE_EVENTS.has(event.event)) {
        return null
    }
    // captureToolbarException tags the toolbar's own failures. Anything else is host page code.
    if (event.event === '$exception' && !event.properties?.toolbar_context) {
        return null
    }
    return event
}

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
        // The toolbar runs on customer pages and must not collect anything about them. Each of
        // these is enabled by the internal project's remote config when left unset.
        capture_exceptions: false,
        capture_performance: false,
        capture_heatmaps: false,
        capture_dead_clicks: false,
        capture_pageview: false,
        capture_pageleave: false,
        before_send: dropHostPageCapture,
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
