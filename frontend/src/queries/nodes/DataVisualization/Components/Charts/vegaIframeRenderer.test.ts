import { waitFor } from '@testing-library/react'

import { POSTHOG_RESULTS_DATASET } from '../../generatedVegaLiteUtils'
import {
    VEGA_IFRAME_ERROR_MESSAGE,
    VEGA_IFRAME_RENDERED_MESSAGE,
    VEGA_IFRAME_RENDER_MESSAGE,
} from './vegaIframeMessages'

const mockVegaEmbed = jest.fn(async (container: HTMLElement) => {
    container.appendChild(document.createElement('canvas'))
    return {
        view: {
            data: jest.fn().mockReturnThis(),
            finalize: jest.fn(),
            runAsync: jest.fn(async () => undefined),
        },
    }
})

jest.mock('vega', () => ({
    loader: () => ({
        load: jest.fn(async () => '[]'),
    }),
}))

jest.mock('vega-embed', () => ({
    __esModule: true,
    default: (...args: unknown[]) => mockVegaEmbed(...args),
}))

describe('vegaIframeRenderer', () => {
    beforeEach(() => {
        jest.resetModules()
        document.body.innerHTML = ''
        mockVegaEmbed.mockClear()
    })

    afterEach(() => {
        document.body.innerHTML = ''
        jest.restoreAllMocks()
    })

    it('resolves the iframe container when rendering, not when the script loads', async () => {
        const postMessage = jest.spyOn(window.parent, 'postMessage').mockImplementation()

        await import('./vegaIframeRenderer')
        document.body.innerHTML = '<div id="vis"></div>'

        window.dispatchEvent(
            new MessageEvent('message', {
                data: {
                    type: VEGA_IFRAME_RENDER_MESSAGE,
                    id: 'render-after-container-mount',
                    spec: {
                        $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
                        data: { name: POSTHOG_RESULTS_DATASET },
                        mark: 'bar',
                    },
                    dataRows: [{ name: 'alpha', count: 4 }],
                    datasetName: POSTHOG_RESULTS_DATASET,
                    theme: {
                        axisColor: '#778899',
                        backgroundColor: '#ffffff',
                        colorPalette: ['#ff0000'],
                        gridColor: '#eeeeee',
                        mode: 'light',
                        secondaryTextColor: '#666666',
                        textColor: '#111111',
                    },
                },
            })
        )

        await waitFor(() => expect(mockVegaEmbed).toHaveBeenCalled())
        expect(postMessage).toHaveBeenCalledWith(
            expect.objectContaining({
                id: 'render-after-container-mount',
                type: VEGA_IFRAME_RENDERED_MESSAGE,
            }),
            '*'
        )
        expect(postMessage).not.toHaveBeenCalledWith(
            expect.objectContaining({
                error: 'Vega iframe container was not found.',
                type: VEGA_IFRAME_ERROR_MESSAGE,
            }),
            '*'
        )
    })
})
