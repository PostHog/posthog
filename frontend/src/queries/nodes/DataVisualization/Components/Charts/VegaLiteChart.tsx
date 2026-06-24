import clsx from 'clsx'
import { useValues } from 'kea'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { buildTheme } from 'lib/charts/utils/theme'
import { objectsEqual } from 'lib/utils/objects'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'
import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import {
    GENERATED_VEGA_LITE_VIEW_ATTR,
    POSTHOG_RESULTS_DATASET,
    buildVegaLiteDataRows,
} from '../../generatedVegaLiteUtils'
import type { SQLVisualizationGenerationField, ValidatedVegaLiteSpec } from '../../generatedVegaLiteUtils'
import {
    VEGA_IFRAME_ERROR_MESSAGE,
    VEGA_IFRAME_READY_MESSAGE,
    VEGA_IFRAME_RENDERED_MESSAGE,
    VEGA_IFRAME_RENDER_MESSAGE,
} from './vegaIframeMessages'
import type { VegaIframeMessage, VegaIframeTheme } from './vegaIframeMessages'

export interface VegaLiteChartProps {
    response: HogQLQueryResponse
    spec: ValidatedVegaLiteSpec
    fields: SQLVisualizationGenerationField[]
    className?: string
    onRenderError?: (error: string) => void
    onRenderSuccess?: () => void
}

const VEGA_IFRAME_RENDERER_ASSET_VERSION = '2'
const VEGA_IFRAME_RENDERER_HTML = `vega-iframe-renderer.html?v=${VEGA_IFRAME_RENDERER_ASSET_VERSION}`
const RENDER_TIMEOUT_MS = 10000
const DEFAULT_IFRAME_HEIGHT = 320

const cssVariable = (name: string, fallback: string): string => {
    if (typeof document === 'undefined') {
        return fallback
    }

    const bodyValue = getComputedStyle(document.body).getPropertyValue(name).trim()
    if (bodyValue) {
        return bodyValue
    }

    return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

const staticAssetUrl = (asset: string): string => {
    const baseUrl = window.JS_URL?.replace(/\/$/, '') ?? ''
    return `${baseUrl}/static/${asset}`
}

const buildIframeTheme = (isDarkModeOn: boolean): VegaIframeTheme => {
    const chartTheme = buildTheme()

    return {
        axisColor: chartTheme.axisColor ?? cssVariable('--color-graph-axis', isDarkModeOn ? '#9ca3af' : '#6b7280'),
        backgroundColor:
            chartTheme.backgroundColor ??
            cssVariable('--color-bg-surface-primary', isDarkModeOn ? '#1f2937' : '#ffffff'),
        colorPalette: chartTheme.colors.length ? chartTheme.colors : ['#1d4aff', '#f54e00', '#f9bd2b'],
        gridColor: chartTheme.gridColor ?? cssVariable('--color-graph-axis-line', isDarkModeOn ? '#374151' : '#e5e7eb'),
        mode: isDarkModeOn ? 'dark' : 'light',
        secondaryTextColor: cssVariable('--color-text-secondary', isDarkModeOn ? '#d1d5db' : '#4b5563'),
        textColor: cssVariable('--color-text-primary', isDarkModeOn ? '#f9fafb' : '#111827'),
    }
}

function useDeepStableValue<T>(value: T): T {
    const valueRef = useRef(value)
    if (!objectsEqual(valueRef.current, value)) {
        valueRef.current = value
    }
    return valueRef.current
}

export function VegaLiteChart({
    response,
    spec,
    fields,
    className,
    onRenderError,
    onRenderSuccess,
}: VegaLiteChartProps): JSX.Element {
    const iframeRef = useRef<HTMLIFrameElement | null>(null)
    const renderTimeoutRef = useRef<number | null>(null)
    const pendingRenderIdRef = useRef<string | null>(null)
    const rendererReadyRef = useRef(false)
    const renderCountRef = useRef(0)
    const [renderError, setRenderError] = useState<string | null>(null)
    const [iframeHeight, setIframeHeight] = useState(DEFAULT_IFRAME_HEIGHT)
    const [iframeKey, setIframeKey] = useState(0)
    const { isDarkModeOn } = useValues(themeLogic)
    const stableSpec = useDeepStableValue(spec)
    const stableFields = useDeepStableValue(fields)
    const dataRows = useMemo(() => buildVegaLiteDataRows(response, stableFields), [response, stableFields])
    const iframeSrc = useMemo(() => staticAssetUrl(VEGA_IFRAME_RENDERER_HTML), [])
    const iframeTheme = useMemo(() => buildIframeTheme(isDarkModeOn), [isDarkModeOn])

    const clearRenderTimeout = useCallback((): void => {
        if (renderTimeoutRef.current !== null) {
            window.clearTimeout(renderTimeoutRef.current)
            renderTimeoutRef.current = null
        }
    }, [])

    const reportRenderError = useCallback(
        (message: string): void => {
            clearRenderTimeout()
            pendingRenderIdRef.current = null
            rendererReadyRef.current = false
            if (onRenderError) {
                onRenderError(message)
            } else {
                setRenderError(message)
            }
            setIframeKey((key) => key + 1)
        },
        [clearRenderTimeout, onRenderError]
    )

    const sendRenderMessage = useCallback((): void => {
        const iframeWindow = iframeRef.current?.contentWindow
        if (!iframeWindow || !rendererReadyRef.current) {
            return
        }

        const renderId = `generated-vega-${Date.now()}-${renderCountRef.current++}`
        pendingRenderIdRef.current = renderId
        clearRenderTimeout()
        setRenderError(null)

        renderTimeoutRef.current = window.setTimeout(() => {
            if (pendingRenderIdRef.current === renderId) {
                reportRenderError('Rendering timed out in the Vega sandbox.')
            }
        }, RENDER_TIMEOUT_MS)

        iframeWindow.postMessage(
            {
                type: VEGA_IFRAME_RENDER_MESSAGE,
                id: renderId,
                spec: stableSpec,
                dataRows,
                datasetName: POSTHOG_RESULTS_DATASET,
                theme: iframeTheme,
            },
            '*'
        )
    }, [clearRenderTimeout, dataRows, iframeTheme, reportRenderError, stableSpec])

    useEffect(() => {
        return () => {
            clearRenderTimeout()
        }
    }, [clearRenderTimeout])

    useEffect(() => {
        if (rendererReadyRef.current) {
            sendRenderMessage()
        }
    }, [sendRenderMessage])

    useEffect(() => {
        const handleMessage = (event: MessageEvent): void => {
            if (event.source !== iframeRef.current?.contentWindow) {
                return
            }

            const message = event.data as VegaIframeMessage
            if (!message || typeof message !== 'object') {
                return
            }

            if (message.type === VEGA_IFRAME_READY_MESSAGE) {
                rendererReadyRef.current = true
                if (!pendingRenderIdRef.current) {
                    sendRenderMessage()
                }
                return
            }

            if (message.type === VEGA_IFRAME_RENDERED_MESSAGE) {
                if (pendingRenderIdRef.current === message.id) {
                    clearRenderTimeout()
                    pendingRenderIdRef.current = null
                    setIframeHeight(Math.max(DEFAULT_IFRAME_HEIGHT, Math.ceil(message.height ?? DEFAULT_IFRAME_HEIGHT)))
                    setRenderError(null)
                    onRenderSuccess?.()
                }
                return
            }

            if (message.type === VEGA_IFRAME_ERROR_MESSAGE) {
                if (!message.id || pendingRenderIdRef.current === message.id) {
                    reportRenderError(message.error)
                }
            }
        }

        window.addEventListener('message', handleMessage)
        return () => {
            window.removeEventListener('message', handleMessage)
        }
    }, [clearRenderTimeout, onRenderSuccess, reportRenderError, sendRenderMessage])

    useEffect(() => {
        setRenderError(null)
        setIframeHeight(DEFAULT_IFRAME_HEIGHT)
    }, [dataRows, iframeTheme, stableSpec])

    if (renderError) {
        return (
            <div className={clsx('flex flex-col gap-2 p-3', className)} data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}>
                <LemonBanner type="warning">Could not render the generated chart: {renderError}</LemonBanner>
            </div>
        )
    }

    return (
        <iframe
            key={iframeKey}
            ref={iframeRef}
            className={clsx('w-full min-h-80 border-0 bg-surface-primary', className)}
            data-attr={GENERATED_VEGA_LITE_VIEW_ATTR}
            height={iframeHeight}
            referrerPolicy="no-referrer"
            sandbox="allow-scripts"
            src={iframeSrc}
            title="Generated Vega visualization"
            onLoad={() => {
                const wasReady = rendererReadyRef.current
                rendererReadyRef.current = true
                if (!wasReady && !pendingRenderIdRef.current) {
                    sendRenderMessage()
                }
            }}
        />
    )
}
