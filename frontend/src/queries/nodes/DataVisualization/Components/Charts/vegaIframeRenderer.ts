import * as vega from 'vega'
import type { Loader } from 'vega'
import vegaEmbed from 'vega-embed'

import { POSTHOG_RESULTS_DATASET } from '../../generatedVegaLiteUtils'
import type { ValidatedVegaLiteSpec } from '../../generatedVegaLiteUtils'
import {
    VEGA_IFRAME_ERROR_MESSAGE,
    VEGA_IFRAME_READY_MESSAGE,
    VEGA_IFRAME_RENDERED_MESSAGE,
    VEGA_IFRAME_RENDER_MESSAGE,
} from './vegaIframeMessages'
import type {
    VegaIframeErrorMessage,
    VegaIframeMessage,
    VegaIframeRenderMessage,
    VegaIframeTheme,
} from './vegaIframeMessages'

interface VegaView {
    data: (name: string, values: Record<string, unknown>[]) => VegaView
    finalize: () => void
    runAsync: () => Promise<unknown>
}

interface VegaEmbedResult {
    view: VegaView
}

type PlainObject = Record<string, unknown>

let embedResult: VegaEmbedResult | null = null

const isPlainObject = (value: unknown): value is PlainObject =>
    typeof value === 'object' && value !== null && !Array.isArray(value)

const postToParent = (message: VegaIframeMessage): void => {
    window.parent.postMessage(message, '*')
}

const postError = (id: string | undefined, error: unknown): void => {
    const message: VegaIframeErrorMessage = {
        type: VEGA_IFRAME_ERROR_MESSAGE,
        id,
        error: error instanceof Error ? error.message : 'Could not render the generated chart.',
    }
    postToParent(message)
}

const isRawVegaSpec = (spec: PlainObject): boolean => {
    if (typeof spec.$schema === 'string') {
        return spec.$schema.includes('/schema/vega/')
    }

    return ['marks', 'signals', 'scales', 'axes', 'legends'].some((key) => Array.isArray(spec[key]))
}

const deepMergeDefaults = (defaults: PlainObject, value: unknown): PlainObject => {
    if (!isPlainObject(value)) {
        return defaults
    }

    const merged: PlainObject = { ...defaults }
    Object.entries(value).forEach(([key, nestedValue]) => {
        const defaultValue = merged[key]
        merged[key] =
            isPlainObject(defaultValue) && isPlainObject(nestedValue)
                ? deepMergeDefaults(defaultValue, nestedValue)
                : nestedValue
    })
    return merged
}

const buildThemeConfig = (theme: VegaIframeTheme): PlainObject => ({
    axis: {
        domainColor: theme.axisColor,
        gridColor: theme.gridColor,
        labelColor: theme.secondaryTextColor,
        tickColor: theme.axisColor,
        titleColor: theme.textColor,
    },
    axisX: {
        gridColor: theme.gridColor,
    },
    axisY: {
        gridColor: theme.gridColor,
    },
    legend: {
        labelColor: theme.secondaryTextColor,
        titleColor: theme.textColor,
    },
    range: {
        category: theme.colorPalette,
        ordinal: theme.colorPalette,
    },
    title: {
        color: theme.textColor,
        subtitleColor: theme.secondaryTextColor,
    },
    view: {
        stroke: 'transparent',
    },
})

const applyThemeDefaults = (spec: ValidatedVegaLiteSpec, theme: VegaIframeTheme): ValidatedVegaLiteSpec => {
    const themedSpec = JSON.parse(JSON.stringify(spec)) as PlainObject

    if (themedSpec.background === undefined) {
        themedSpec.background = theme.backgroundColor
    }

    themedSpec.config = deepMergeDefaults(buildThemeConfig(theme), themedSpec.config)
    return themedSpec
}

const referencesNamedDataset = (value: unknown, datasetName: string): boolean => {
    if (Array.isArray(value)) {
        return value.some((item) => referencesNamedDataset(item, datasetName))
    }

    if (!isPlainObject(value)) {
        return false
    }

    if (value.name === datasetName || value.data === datasetName) {
        return true
    }

    return Object.values(value).some((nestedValue) => referencesNamedDataset(nestedValue, datasetName))
}

const createLoader = (dataRows: Record<string, unknown>[], datasetName: string): Loader => {
    const baseLoader = vega.loader()
    const posthogDatasetUrls = new Set([
        `posthog://${datasetName}`,
        `posthog://dataset/${datasetName}`,
        `posthog://${POSTHOG_RESULTS_DATASET}`,
        `posthog://dataset/${POSTHOG_RESULTS_DATASET}`,
    ])

    return {
        ...baseLoader,
        load: async (uri: string, options?: Parameters<Loader['load']>[1]): Promise<string> => {
            if (posthogDatasetUrls.has(uri)) {
                return JSON.stringify(dataRows)
            }

            return baseLoader.load(uri, options)
        },
    }
}

const render = async ({ id, spec, dataRows, datasetName, theme }: VegaIframeRenderMessage): Promise<void> => {
    const container = document.getElementById('vis')
    if (!container) {
        throw new Error('Vega iframe container was not found.')
    }

    embedResult?.view.finalize()
    embedResult = null
    container.replaceChildren()
    document.body.setAttribute('theme', theme.mode)
    document.body.style.backgroundColor = theme.backgroundColor
    document.documentElement.style.backgroundColor = theme.backgroundColor

    const themedSpec = applyThemeDefaults(spec, theme)
    const loader = createLoader(dataRows, datasetName)

    embedResult = (await vegaEmbed(container, themedSpec, {
        actions: false,
        ast: true,
        loader,
        renderer: 'canvas',
    })) as unknown as VegaEmbedResult

    if (
        referencesNamedDataset(themedSpec, datasetName) ||
        referencesNamedDataset(themedSpec, POSTHOG_RESULTS_DATASET)
    ) {
        embedResult.view.data(datasetName, dataRows)
        if (datasetName !== POSTHOG_RESULTS_DATASET) {
            embedResult.view.data(POSTHOG_RESULTS_DATASET, dataRows)
        }
        await embedResult.view.runAsync()
    }

    const boundsHeight = isRawVegaSpec(themedSpec)
        ? container.getBoundingClientRect().height
        : Math.ceil(container.getBoundingClientRect().height)

    postToParent({
        type: VEGA_IFRAME_RENDERED_MESSAGE,
        id,
        height: Number.isFinite(boundsHeight) && boundsHeight > 0 ? boundsHeight : undefined,
    })
}

window.addEventListener('message', (event: MessageEvent) => {
    const message = event.data as VegaIframeMessage
    if (!message || message.type !== VEGA_IFRAME_RENDER_MESSAGE) {
        return
    }

    void render(message).catch((error) => postError(message.id, error))
})

window.addEventListener('pagehide', () => {
    embedResult?.view.finalize()
})

postToParent({ type: VEGA_IFRAME_READY_MESSAGE })
