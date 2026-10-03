import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { Table } from './Table'

const paragraph = 'First paragraph with a longer description.\n\nSecond paragraph with more detail.'
const jsonText = '{"message":"<b>Keep this as text</b>"}'
const url = `https://example.com/${'long-path-'.repeat(40)}`
const cachedResults: HogQLQueryResponse = {
    columns: ['prompt', 'compact'],
    types: [
        ['prompt', 'Nullable(String)'],
        ['compact', 'String'],
    ],
    results: [
        [paragraph, 'First result'],
        [jsonText, 'Second result'],
        [null, 'Third result'],
        [url, 'Fourth result'],
    ],
}

describe('Table text wrapping', () => {
    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it.each([false, true])('wraps only the configured source column when transpose is %s', async (transpose) => {
        initKeaTests()
        const key = `table-wrapping-${transpose}`
        const query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select prompt, compact from examples' },
            display: ChartDisplayType.ActionsTable,
            tableSettings: {
                transpose,
                columns: [{ column: 'prompt', settings: { display: { wrapText: true } } }, { column: 'compact' }],
            },
        }
        const props: DataVisualizationLogicProps = { key, query, cachedResults, dataNodeCollectionId: key }
        const dataProps = { key, query: query.source, cachedResults, dataNodeCollectionId: key }
        dataNodeLogic(dataProps).mount()
        dataVisualizationLogic(props).mount()

        const { container } = render(
            <BindLogic logic={dataNodeLogic} props={dataProps}>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <Table uniqueKey={key} query={query} cachedResults={cachedResults} context={undefined} />
                </BindLogic>
            </BindLogic>
        )

        const text = await screen.findByText(
            (_, element) => element?.textContent === paragraph && element.tagName === 'DIV'
        )
        expect(text).toHaveClass('whitespace-pre-wrap')
        expect(text).not.toHaveClass('truncate')
        await waitFor(() =>
            expect(container.querySelector('.whitespace-pre-wrap .react-json-view')).toBeInTheDocument()
        )
        expect(container.querySelector('b')).toBeNull()
        expect(screen.getByText('First result').closest('.truncate')).not.toBeNull()
        expect(screen.getByText('—')).toBeInTheDocument()
        const link = screen.getByRole('link')
        expect(link).toHaveAttribute('href', url)
        expect(link).toHaveTextContent(url)
        expect(link.closest('.line-clamp-3')).toBeNull()
    })

    it.each([false, true])('preserves specialized cells when wrapped and transpose is %s', async (transpose) => {
        jest.useFakeTimers({ now: new Date('2025-01-01T14:00:00Z'), advanceTimers: true })
        initKeaTests()
        const key = `table-wrapping-renderers-${transpose}`
        const results: HogQLQueryResponse = {
            columns: ['date', 'properties.$session_id', 'json'],
            types: [
                ['date', 'String'],
                ['properties.$session_id', 'String'],
                ['json', 'String'],
            ],
            results: [['2025-01-01T12:00:00Z', '01900000-0000-7000-8000-000000000001', '{"answer":42}']],
        }
        const query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select date, properties.$session_id, json from examples' },
            display: ChartDisplayType.ActionsTable,
            tableSettings: {
                transpose,
                columns: results.columns.map((column) => ({ column, settings: { display: { wrapText: true } } })),
            },
        }
        const props: DataVisualizationLogicProps = { key, query, cachedResults: results, dataNodeCollectionId: key }
        const dataProps = { key, query: query.source, cachedResults: results, dataNodeCollectionId: key }
        dataNodeLogic(dataProps).mount()
        dataVisualizationLogic(props).mount()

        const { container } = render(
            <BindLogic logic={dataNodeLogic} props={dataProps}>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <Table uniqueKey={key} query={query} cachedResults={results} context={undefined} />
                </BindLogic>
            </BindLogic>
        )

        expect(await screen.findByText('2 hours ago')).toBeInTheDocument()
        expect(screen.getByText('01900000-0000-7000-8000-000000000001').closest('a')).toHaveAttribute(
            'href',
            '/project/997/sessions/01900000-0000-7000-8000-000000000001'
        )
        await waitFor(() => expect(container.querySelector('.react-json-view')).toBeInTheDocument())
    })
})
