import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { DataVisualizationNode, HogQLQueryResponse } from '~/queries/schema/schema-general'

import { POSTHOG_RESULTS_DATASET } from '../../generatedVegaLiteUtils'
import type { SQLVisualizationGenerationField, ValidatedVegaLiteSpec } from '../../generatedVegaLiteUtils'
import { GeneratedVegaLiteVisualization } from './GeneratedVegaLiteVisualization'
import { VEGA_IFRAME_RENDERED_MESSAGE } from './vegaIframeMessages'

let mockKeaValues: Record<string, unknown>
let mockKeaActions: Record<string, jest.Mock>

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: () => mockKeaActions,
    useValues: () => mockKeaValues,
}))

jest.mock('../Table', () => ({
    Table: (): JSX.Element => <div data-testid="table-fallback" />,
}))

jest.mock('lib/charts/utils/theme', () => ({
    buildTheme: () => ({
        axisColor: '#778899',
        backgroundColor: '#ffffff',
        colors: ['#ff0000', '#00ff00'],
        gridColor: '#ddeeff',
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

const query = {
    kind: 'DataVisualizationNode',
    source: {
        kind: 'HogQLQuery',
        query: 'select 1',
    },
} as DataVisualizationNode

describe('GeneratedVegaLiteVisualization', () => {
    beforeEach(() => {
        window.JS_URL = 'https://static.example.com'
        mockKeaActions = {
            generateVegaLiteChart: jest.fn(),
            updateChartSettings: jest.fn(),
        }
        mockKeaValues = {
            chartSettings: {
                generatedVegaLite: {
                    fields,
                    renderError: 'Vega iframe container was not found.',
                    validatedSpec: spec,
                },
            },
            columns: ['name', 'count'],
            generatedVegaLiteResponseLoading: false,
            isDarkModeOn: false,
            response,
        }
    })

    afterEach(() => {
        cleanup()
        window.JS_URL = undefined
    })

    it('retries a valid saved spec instead of blocking on a stale render error', async () => {
        render(<GeneratedVegaLiteVisualization query={query} />)

        expect(screen.queryByText(/Render failed:/)).not.toBeInTheDocument()
        expect(screen.queryByTestId('table-fallback')).not.toBeInTheDocument()

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

        expect(mockKeaActions.updateChartSettings).toHaveBeenCalledWith({
            generatedVegaLite: {
                renderError: undefined,
            },
        })
    })
})
