import { actions, afterMount, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { WebVitalsMetric } from '~/queries/schema'
import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'

import type { webVitalsToolbarLogicType } from './webVitalsToolbarLogicType'

// We're giving different meaning for `undefined` and `null` here.
// `undefined` means we don't have a value yet, while `null` means we didn't get a value from the server.
export type WebVitalsMetrics = Record<WebVitalsMetric, number | null | undefined>

// It returns this and much more, but we only care about the metrics
export type WebVitalsMetricsResponse = {
    results: {
        action: { custom_name: WebVitalsMetric }
        data: [number, number] // We care about the second value, last one from the week
    }[]
}

export const webVitalsToolbarLogic = kea<webVitalsToolbarLogicType>([
    path(['toolbar', 'web-vitals', 'webVitalsToolbarLogic']),
    connect(() => ({
        values: [toolbarConfigLogic, ['posthog']],
    })),
    actions({
        getWebVitals: true,
        setLocalWebVital: (webVitalMetric: WebVitalsMetric, value: number | null) => ({ webVitalMetric, value }),
        clearLocalWebVitals: true,
    }),

    reducers({
        localWebVitals: [
            {} as WebVitalsMetrics,
            {
                setLocalWebVital: (state, { webVitalMetric, value }) => ({
                    ...state,
                    [webVitalMetric]: value,
                }),
                clearLocalWebVitals: () => ({} as WebVitalsMetrics),
            },
        ],
    }),

    loaders(() => ({
        remoteWebVitals: [
            {} as WebVitalsMetrics,
            {
                getWebVitals: async (_, breakpoint) => {
                    const params = { pathname: window.location.pathname }

                    const response = await toolbarFetch(
                        `/api/environments/@current/web_vitals${encodeParams(params, '?')}`
                    )
                    breakpoint()

                    if (!response.ok) {
                        return { LCP: null, FCP: null, CLS: null, INP: null } as WebVitalsMetrics
                    }

                    const json = (await response.json()) as WebVitalsMetricsResponse
                    breakpoint()

                    return {
                        LCP: json.results.find((result) => result.action.custom_name === 'LCP')?.data[1] ?? null,
                        FCP: json.results.find((result) => result.action.custom_name === 'FCP')?.data[1] ?? null,
                        CLS: json.results.find((result) => result.action.custom_name === 'CLS')?.data[1] ?? null,
                        INP: json.results.find((result) => result.action.custom_name === 'INP')?.data[1] ?? null,
                    }
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        urlChanged: () => {
            actions.clearLocalWebVitals()
            actions.getWebVitals()
        },
    })),
    afterMount(({ values, actions }) => {
        // Listen to history state changes for SPA navigation
        window.addEventListener('popstate', () => {
            actions.clearLocalWebVitals()
            actions.getWebVitals()
        })

        // Listen to pushState and replaceState calls
        const originalPushState = window.history.pushState.bind(window.history)
        const originalReplaceState = window.history.replaceState.bind(window.history)

        window.history.pushState = function (...args) {
            originalPushState(...args)
            actions.clearLocalWebVitals()
            actions.getWebVitals()
        }

        window.history.replaceState = function (...args) {
            originalReplaceState(...args)
            actions.clearLocalWebVitals()
            actions.getWebVitals()
        }

        // Listen to posthog events and capture them
        const METRICS_AND_PROPERTIES: Record<WebVitalsMetric, string> = {
            FCP: '$web_vitals_FCP_value',
            LCP: '$web_vitals_LCP_value',
            CLS: '$web_vitals_CLS_value',
            INP: '$web_vitals_INP_value',
        }
        values.posthog?.on('eventCaptured', (event) => {
            if (event.event === '$web_vitals') {
                for (const [metric, property] of Object.entries(METRICS_AND_PROPERTIES)) {
                    const value = event.properties[property]
                    if (value !== undefined) {
                        actions.setLocalWebVital(metric as WebVitalsMetric, value)
                    }
                }
            }
        })

        // Collect the web vitals metrics from the server
        actions.getWebVitals()
    }),
    permanentlyMount(),
])
