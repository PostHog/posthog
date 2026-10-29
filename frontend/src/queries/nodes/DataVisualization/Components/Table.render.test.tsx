import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic } from 'kea'

import * as hog from 'lib/hog'
import { themeLogic } from 'lib/logic/themeLogic'
import { userLogic } from 'scenes/userLogic'

import {
    ConditionalFormattingRule,
    HogQLQueryResponse,
    NodeKind,
    VisualizationNode,
} from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { HogQLBoldNumber } from 'products/product_analytics/frontend/insights/shared/BoldNumber/BoldNumber'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { dataVisualizationLogic } from '../dataVisualizationLogic'
import { Table } from './Table'

const response: HogQLQueryResponse = {
    columns: ['region', 'value'],
    types: [
        ['region', 'String'],
        ['value', 'Float64'],
    ],
    results: [
        ['US', 10],
        ['EU', 0],
    ],
}

const query: VisualizationNode = {
    kind: NodeKind.DataVisualizationNode,
    source: { kind: NodeKind.HogQLQuery, query: 'select region, value from results' },
    display: ChartDisplayType.ActionsTable,
    tableSettings: {
        columns: [{ column: 'region' }, { column: 'value', settings: { formatting: { prefix: 'USD ' } } }],
    },
}

function mountResult(
    node: VisualizationNode,
    cachedResults: HogQLQueryResponse
): {
    logic: ReturnType<typeof dataVisualizationLogic.build>
    props: { key: string; dataNodeCollectionId: string; query: VisualizationNode; cachedResults: HogQLQueryResponse }
    sourceProps: {
        key: string
        dataNodeCollectionId: string
        query: VisualizationNode['source']
        cachedResults: HogQLQueryResponse
    }
} {
    const props = {
        key: 'table-removal-regression',
        dataNodeCollectionId: 'table-removal-regression',
        query: node,
        cachedResults,
    }
    const sourceProps = { ...props, query: node.source }
    dataNodeLogic(sourceProps).mount()
    const logic = dataVisualizationLogic(props)
    logic.mount()
    return { logic, props, sourceProps }
}

describe('SQL table rendering', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([false, true])('inspects the original row after sorting or transposing, transpose=%s', (transpose) => {
        const node = { ...query, tableSettings: { ...query.tableSettings, transpose } }
        const { props, sourceProps } = mountResult(node, response)
        const onInspect = jest.fn()
        render(
            <BindLogic logic={dataNodeLogic} props={sourceProps}>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <Table
                        query={node}
                        uniqueKey={props.key}
                        context={{}}
                        cachedResults={response}
                        onInspect={onInspect}
                    />
                </BindLogic>
            </BindLogic>
        )
        if (!transpose) {
            fireEvent.click(screen.getByText('region').closest('.LemonTable__header-content')!)
        }
        expect(screen.getByText('EU').closest('tbody')!.querySelector('tr[data-row-key]')).toHaveTextContent(
            transpose ? 'US' : 'EU'
        )
        fireEvent.click(screen.getByText('USD 10').closest('button')!)
        expect(onInspect).toHaveBeenLastCalledWith({ region: 'US', value: 10 })
        fireEvent.click(screen.getByText('USD 0').closest('button')!)
        expect(onInspect).toHaveBeenLastCalledWith({ region: 'EU', value: 0 })
    })

    it('updates conditional cell colors when rules and results change', async () => {
        const rule: ConditionalFormattingRule = {
            id: 'equals',
            templateId: 'equals',
            columnName: 'value',
            input: '10',
            color: '#FFADAD',
            colorMode: 'light',
            bytecode: ['_H', 1, 32, 'input', 1, 1, 32, 'value', 1, 1, 11, 38],
        }
        const node = { ...query, tableSettings: { ...query.tableSettings, conditionalFormatting: [rule] } }
        const { logic, props, sourceProps } = mountResult(node, response)
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, theme_mode: 'light' })
        logic.actions.setHogVm(hog)
        render(
            <BindLogic logic={dataNodeLogic} props={sourceProps}>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <Table query={node} uniqueKey={props.key} context={{}} cachedResults={response} />
                </BindLogic>
            </BindLogic>
        )
        await waitFor(() =>
            expect(screen.getByText('USD 10').closest('td')).toHaveStyle({ backgroundColor: '#FFADAD' })
        )
        expect(screen.getByText('USD 0').closest('td')).not.toHaveStyle({ backgroundColor: '#FFADAD' })

        act(() =>
            logic.actions._setQuery({
                ...node,
                tableSettings: { ...node.tableSettings, conditionalFormatting: [{ ...rule, color: '#CAFFBF' }] },
            })
        )
        expect(screen.getByText('USD 10').closest('td')).toHaveStyle({ backgroundColor: '#CAFFBF' })

        act(() =>
            dataNodeLogic(sourceProps).actions.setResponse({
                ...response,
                results: [
                    ['US', 0],
                    ['EU', 10],
                ],
            })
        )
        expect(screen.getByText('USD 10').closest('td')).toHaveStyle({ backgroundColor: '#CAFFBF' })
        expect(screen.getByText('USD 0').closest('td')).not.toHaveStyle({ backgroundColor: '#CAFFBF' })
        act(() => userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, theme_mode: 'dark' }))
        expect(themeLogic.values.isDarkModeOn).toBe(true)
        expect(screen.getByText('USD 10').closest('td')).not.toHaveStyle({ backgroundColor: '#CAFFBF' })
        act(() => userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, theme_mode: 'light' }))
        expect(screen.getByText('USD 10').closest('td')).toHaveStyle({ backgroundColor: '#CAFFBF' })
    })

    it('does not format cells on every sort comparison', () => {
        const localeFormat = jest.spyOn(Number.prototype, 'toLocaleString').mockImplementation(function (this: number) {
            return String(this.valueOf())
        })
        const rowCount = 1000
        const result: HogQLQueryResponse = {
            columns: ['value'],
            types: [['value', 'Float64']],
            results: Array.from({ length: rowCount }, (_, index) => [(index * 7919 + 17) % rowCount]),
        }
        const node = {
            ...query,
            tableSettings: { columns: [{ column: 'value', settings: { formatting: { style: 'number' as const } } }] },
        }
        try {
            const { props, sourceProps } = mountResult(node, result)
            const { container } = render(
                <BindLogic logic={dataNodeLogic} props={sourceProps}>
                    <BindLogic logic={dataVisualizationLogic} props={props}>
                        <Table query={node} uniqueKey={props.key} context={{}} cachedResults={result} />
                    </BindLogic>
                </BindLogic>
            )
            localeFormat.mockClear()
            fireEvent.click(screen.getByText('value').closest('.LemonTable__header-content')!)
            expect(container.querySelector('tbody tr[data-row-key]')).toHaveTextContent('0')
            expect(localeFormat.mock.calls.length).toBeGreaterThan(0)
            expect(localeFormat.mock.calls.length).toBeLessThanOrEqual(rowCount * 3)

            act(() =>
                dataNodeLogic(sourceProps).actions.setResponse({
                    ...result,
                    results: Array.from({ length: rowCount }, (_, index) => [-index]),
                })
            )
            expect(container.querySelector('tbody tr[data-row-key]')).toHaveTextContent('-999')
        } finally {
            cleanup()
            localeFormat.mockRestore()
        }
    })

    it.each([
        { embedded: true, virtualized: false, pinned: false },
        { embedded: false, virtualized: true, pinned: false },
        { embedded: true, virtualized: true, pinned: true },
    ])('keeps the full column layout for $embedded/$virtualized/$pinned', ({ embedded, virtualized, pinned }) => {
        const height = jest.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockReturnValue(180)
        const width = jest.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(800)
        const columns = Array.from({ length: 60 }, (_, index) => `column_${index}`)
        const result: HogQLQueryResponse = {
            columns,
            types: columns.map((column) => [column, 'String']),
            results: [columns.map((_, index) => `value_${index}`)],
        }
        const node = {
            ...query,
            tableSettings: { pinnedColumns: pinned ? [columns[0]] : [] },
        }
        try {
            const { props, sourceProps } = mountResult(node, result)
            const { container } = render(
                <BindLogic logic={dataNodeLogic} props={sourceProps}>
                    <BindLogic logic={dataVisualizationLogic} props={props}>
                        <Table
                            query={node}
                            uniqueKey={props.key}
                            context={{ dataVisualizationTableVirtualized: virtualized }}
                            cachedResults={result}
                            embedded={embedded}
                        />
                    </BindLogic>
                </BindLogic>
            )
            expect(container.querySelectorAll('tbody td:not([aria-hidden])')).toHaveLength(60)
            expect(screen.getByText('value_59')).toBeVisible()
        } finally {
            cleanup()
            height.mockRestore()
            width.mockRestore()
        }
    })

    it.each([
        { results: [[10]], expected: 'USD 10' },
        { results: [[0]], expected: 'USD 0' },
        { results: [], expected: null },
        { results: [[null]], expected: null },
    ])('renders SQL big numbers for $results', ({ results, expected }) => {
        const node = { ...query, display: ChartDisplayType.BoldNumber }
        const result: HogQLQueryResponse = { columns: ['value'], types: [['value', 'Float64']], results }
        const { props, sourceProps } = mountResult(node, result)
        const { container } = render(
            <BindLogic logic={dataNodeLogic} props={sourceProps}>
                <BindLogic logic={dataVisualizationLogic} props={props}>
                    <HogQLBoldNumber />
                </BindLogic>
            </BindLogic>
        )
        expect(container.querySelector('.BoldNumber__value')?.textContent ?? null).toBe(expected)
    })
})
