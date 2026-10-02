import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
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
    afterEach(cleanup)

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
        expect(screen.getByText(jsonText).closest('.whitespace-pre-wrap')).not.toBeNull()
        expect(container.querySelector('b')).toBeNull()
        expect(screen.getByText('First result').closest('.truncate')).not.toBeNull()
        expect(screen.getByText('—')).toBeInTheDocument()
        const link = screen.getByRole('link')
        expect(link).toHaveAttribute('href', url)
        expect(link).toHaveTextContent(url)
        expect(link.closest('.line-clamp-3')).toBeNull()
    })
})
