import type { ValidatedVegaLiteSpec } from '../../generatedVegaLiteUtils'

export const VEGA_IFRAME_READY_MESSAGE = 'posthog:vega-iframe-ready'
export const VEGA_IFRAME_RENDER_MESSAGE = 'posthog:vega-iframe-render'
export const VEGA_IFRAME_RENDERED_MESSAGE = 'posthog:vega-iframe-rendered'
export const VEGA_IFRAME_ERROR_MESSAGE = 'posthog:vega-iframe-error'

export interface VegaIframeTheme {
    axisColor: string
    backgroundColor: string
    colorPalette: string[]
    gridColor: string
    mode: 'light' | 'dark'
    secondaryTextColor: string
    textColor: string
}

export interface VegaIframeRenderMessage {
    dataRows: Record<string, unknown>[]
    datasetName: string
    id: string
    spec: ValidatedVegaLiteSpec
    theme: VegaIframeTheme
    type: typeof VEGA_IFRAME_RENDER_MESSAGE
}

export interface VegaIframeReadyMessage {
    type: typeof VEGA_IFRAME_READY_MESSAGE
}

export interface VegaIframeRenderedMessage {
    height?: number
    id: string
    type: typeof VEGA_IFRAME_RENDERED_MESSAGE
}

export interface VegaIframeErrorMessage {
    error: string
    id?: string
    type: typeof VEGA_IFRAME_ERROR_MESSAGE
}

export type VegaIframeMessage =
    | VegaIframeReadyMessage
    | VegaIframeRenderMessage
    | VegaIframeRenderedMessage
    | VegaIframeErrorMessage
