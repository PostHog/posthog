import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { POSTHOG_RESULTS_DATASET } from '../../generatedVegaLiteUtils'
import type { SQLVisualizationGenerationField, ValidatedVegaLiteSpec } from '../../generatedVegaLiteUtils'
import { VEGA_IFRAME_RENDERED_MESSAGE, VEGA_IFRAME_RENDER_MESSAGE } from './vegaIframeMessages'
import { VegaLiteChart } from './VegaLiteChart'

let mockDarkMode = true

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: () => ({ isDarkModeOn: mockDarkMode }),
}))

jest.mock('lib/charts/utils/theme', () => ({
    buildTheme: () => ({
        axisColor: '#778899',
        backgroundColor: '#101820',
        colors: ['#ff0000', '#00ff00'],
        gridColor: '#223344',
    }),
}))

const response = {
    columns: ['name', 'count'],
    types: [
        ['name', 'String'],
        ['count', 'Int64'],
    ],
    results: [['alpha', 4]],
} as HogQLQueryResponse

const fields: SQLVisualizationGenerationField[] = [
    { field: 'name', sourceColumn: 'name', label: 'name', type: 'String', semanticType: 'nominal' },
    { field: 'count', sourceColumn: 'count', label: 'count', type: 'Int64', semanticType: 'quantitative' },
]

const spec: ValidatedVegaLiteSpec = {
    $schema: 'https://vega.github.io/schema/vega-lite/v6.json',
    data: { name: POSTHOG_RESULTS_DATASET },
    mark: 'bar',
    encoding: {
        x: { field: 'name', type: 'nominal' },
        y: { field: 'count', type: 'quantitative' },
    },
}

describe('VegaLiteChart', () => {
    beforeEach(() => {
        window.JS_URL = 'https://static.example.com'
    })

    afterEach(() => {
        cleanup()
        mockDarkMode = true
        window.JS_URL = undefined
    })

    it('renders through the sandboxed iframe and sends the full spec to the renderer', async () => {
        const onRenderSuccess = jest.fn()
        render(<VegaLiteChart response={response} fields={fields} spec={spec} onRenderSuccess={onRenderSuccess} />)

        const iframe = screen.getByTitle('Generated Vega visualization') as HTMLIFrameElement
        const iframeWindow = iframe.contentWindow
        expect(iframeWindow).toBeTruthy()
        const postMessage = jest.spyOn(iframeWindow as Window, 'postMessage')

        expect(iframe).toHaveAttribute('sandbox', 'allow-scripts')
        expect(iframe).toHaveAttribute('referrerpolicy', 'no-referrer')
        expect(iframe).toHaveAttribute('src', 'https://static.example.com/static/vega-iframe-renderer.html?v=2')

        fireEvent.load(iframe)

        await waitFor(() => expect(postMessage).toHaveBeenCalledWith(expect.any(Object), '*'))
        const renderMessage = postMessage.mock.calls[0][0] as Record<string, unknown>

        expect(renderMessage).toMatchObject({
            type: VEGA_IFRAME_RENDER_MESSAGE,
            dataRows: [{ name: 'alpha', count: 4 }],
            datasetName: POSTHOG_RESULTS_DATASET,
            spec,
            theme: {
                axisColor: '#778899',
                backgroundColor: '#101820',
                colorPalette: ['#ff0000', '#00ff00'],
                gridColor: '#223344',
                mode: 'dark',
            },
        })

        act(() => {
            window.dispatchEvent(
                new MessageEvent('message', {
                    data: {
                        type: VEGA_IFRAME_RENDERED_MESSAGE,
                        id: renderMessage.id,
                        height: 512,
                    },
                    source: iframeWindow,
                })
            )
        })

        expect(iframe).toHaveAttribute('height', '512')
        expect(onRenderSuccess).toHaveBeenCalled()
    })

    it('does not re-render the iframe for cloned equivalent specs and fields', async () => {
        const onRenderSuccess = jest.fn()
        const { rerender } = render(
            <VegaLiteChart response={response} fields={fields} spec={spec} onRenderSuccess={onRenderSuccess} />
        )

        const iframe = screen.getByTitle('Generated Vega visualization') as HTMLIFrameElement
        const iframeWindow = iframe.contentWindow
        expect(iframeWindow).toBeTruthy()
        const postMessage = jest.spyOn(iframeWindow as Window, 'postMessage')

        fireEvent.load(iframe)

        await waitFor(() => expect(postMessage).toHaveBeenCalledWith(expect.any(Object), '*'))
        const renderMessage = postMessage.mock.calls[0][0] as Record<string, unknown>

        act(() => {
            window.dispatchEvent(
                new MessageEvent('message', {
                    data: {
                        type: VEGA_IFRAME_RENDERED_MESSAGE,
                        id: renderMessage.id,
                        height: 512,
                    },
                    source: iframeWindow,
                })
            )
        })

        postMessage.mockClear()

        rerender(
            <VegaLiteChart
                response={response}
                fields={fields.map((field) => ({ ...field }))}
                spec={JSON.parse(JSON.stringify(spec))}
                onRenderSuccess={onRenderSuccess}
            />
        )

        await act(async () => {
            await Promise.resolve()
        })

        expect(postMessage).not.toHaveBeenCalled()
    })
})
