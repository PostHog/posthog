import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { HogQLQueryResponse, VisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { SeriesTab, YSeriesDisplayTab, YSeriesFormattingTab } from './SeriesTab'
import { YSeriesLogicProps } from './ySeriesLogic'

describe('SeriesTab', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        {
            name: 'lists every value column for a proportion bar with no label column',
            display: ChartDisplayType.ActionsProportionBar,
            xAxis: undefined,
            valueColumns: ['signups', 'logins'],
            listsEveryValueColumn: true,
            labelDisabled: true,
        },
        {
            name: 'lists every value column and disables the label when several value columns ignore it',
            display: ChartDisplayType.ActionsProportionBar,
            xAxis: { column: 'day' },
            valueColumns: ['signups', 'logins'],
            listsEveryValueColumn: true,
            labelDisabled: true,
        },
        {
            name: 'picks one value column for a proportion bar grouped by a label column',
            display: ChartDisplayType.ActionsProportionBar,
            xAxis: { column: 'day' },
            valueColumns: ['signups'],
            listsEveryValueColumn: false,
            labelDisabled: false,
        },
        {
            name: 'lists the breakdown parts and disables the label when a breakdown ignores it',
            display: ChartDisplayType.ActionsProportionBar,
            xAxis: { column: 'day' },
            valueColumns: ['signups'],
            seriesBreakdownColumn: 'country',
            listsEveryValueColumn: true,
            labelDisabled: true,
        },
        {
            name: 'lists every value column for a pie with several value columns',
            display: ChartDisplayType.ActionsPie,
            xAxis: { column: 'day' },
            valueColumns: ['signups', 'logins'],
            listsEveryValueColumn: true,
            labelDisabled: true,
        },
        {
            name: 'picks one value column for a pie grouped by a label column',
            display: ChartDisplayType.ActionsPie,
            xAxis: { column: 'day' },
            valueColumns: ['signups'],
            listsEveryValueColumn: false,
            labelDisabled: false,
        },
    ])('$name', ({ display, xAxis, valueColumns, seriesBreakdownColumn, listsEveryValueColumn, labelDisabled }) => {
        initKeaTests()
        const cachedResults: HogQLQueryResponse = {
            results: [['Mon', 3, 5, 'US']],
            columns: ['day', 'signups', 'logins', 'country'],
            types: [
                ['day', 'String'],
                ['signups', 'Float64'],
                ['logins', 'Float64'],
                ['country', 'String'],
            ],
        }
        const query: VisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'select day, signups, logins, country from daily' },
            display,
            chartSettings: { xAxis, yAxis: valueColumns.map((column) => ({ column })), seriesBreakdownColumn },
        }
        const props: DataVisualizationLogicProps = {
            key: `series-tab-part-of-whole-${display}-${!!xAxis}-${valueColumns.length}-${seriesBreakdownColumn}`,
            query,
            cachedResults,
            dataNodeCollectionId: 'series-tab-part-of-whole',
            setQuery: jest.fn(),
        }
        dataNodeLogic({
            key: props.key,
            query: query.source,
            cachedResults,
            dataNodeCollectionId: props.dataNodeCollectionId,
        }).mount()
        dataVisualizationLogic(props).mount()

        const { container } = render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <SeriesTab />
            </BindLogic>
        )

        expect(screen.queryAllByText('Values').length > 0).toBe(listsEveryValueColumn)
        expect(container.querySelector('[data-attr="part-of-whole-label-column"]')?.getAttribute('aria-disabled')).toBe(
            String(labelDisabled)
        )
        expect(screen.queryByRole('button', { name: 'Delete series breakdown' }) !== null).toBe(!!seriesBreakdownColumn)
    })

    it('persists table column formatting changes immediately', async () => {
        initKeaTests()

        const setQuery = jest.fn()
        const query: VisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select region, value from numbers(2)',
            },
            display: ChartDisplayType.ActionsTable,
            tableSettings: {
                columns: [
                    {
                        column: 'value',
                        settings: {
                            formatting: {
                                prefix: '',
                                suffix: '',
                            },
                        },
                    },
                ],
            },
        }

        const props: DataVisualizationLogicProps = {
            key: 'series-tab-test',
            query,
            dataNodeCollectionId: 'series-tab-test',
            setQuery: (setter) => setQuery(setter(query)),
        }

        dataVisualizationLogic(props).mount()
        dataNodeLogic({
            key: props.key,
            query: query.source,
            dataNodeCollectionId: props.dataNodeCollectionId,
        }).mount()

        const ySeriesLogicProps: YSeriesLogicProps = {
            seriesIndex: 0,
            dataVisualizationProps: props,
            series: {
                column: {
                    name: 'value',
                    label: 'value',
                    dataIndex: 1,
                    type: {
                        name: 'FLOAT',
                        isNumerical: true,
                    },
                },
                data: [],
                settings: {
                    formatting: {
                        prefix: '',
                        suffix: '',
                    },
                },
            },
        }

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <YSeriesFormattingTab ySeriesLogicProps={ySeriesLogicProps} />
            </BindLogic>
        )

        const user = userEvent.setup()
        const decimalPlacesInput = await screen.findByRole('spinbutton')
        await user.clear(decimalPlacesInput)
        await user.type(decimalPlacesInput, '2')

        await waitFor(() =>
            expect(setQuery).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    tableSettings: expect.objectContaining({
                        columns: expect.arrayContaining([
                            expect.objectContaining({
                                column: 'value',
                                settings: expect.objectContaining({
                                    formatting: expect.objectContaining({
                                        decimalPlaces: 2,
                                    }),
                                }),
                            }),
                        ]),
                    }),
                })
            )
        )
    })

    it('persists area as a y-axis display type', async () => {
        initKeaTests()

        const setQuery = jest.fn()
        const query: VisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select day, value from numbers(2)',
            },
            display: ChartDisplayType.ActionsLineGraph,
            chartSettings: {
                yAxis: [
                    {
                        column: 'value',
                        settings: {
                            display: {
                                displayType: 'auto',
                            },
                        },
                    },
                ],
            },
        }

        const props: DataVisualizationLogicProps = {
            key: 'series-display-tab-test',
            query,
            dataNodeCollectionId: 'series-display-tab-test',
            setQuery: (setter) => setQuery(setter(query)),
        }

        dataVisualizationLogic(props).mount()
        dataNodeLogic({
            key: props.key,
            query: query.source,
            dataNodeCollectionId: props.dataNodeCollectionId,
        }).mount()

        const ySeriesLogicProps: YSeriesLogicProps = {
            seriesIndex: 0,
            dataVisualizationProps: props,
            series: {
                column: {
                    name: 'value',
                    label: 'value',
                    dataIndex: 1,
                    type: {
                        name: 'FLOAT',
                        isNumerical: true,
                    },
                },
                data: [],
                settings: {
                    display: {
                        displayType: 'auto',
                    },
                },
            },
        }

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <YSeriesDisplayTab ySeriesLogicProps={ySeriesLogicProps} />
            </BindLogic>
        )

        const user = userEvent.setup()
        await user.click(await screen.findByText('Area'))

        await waitFor(() =>
            expect(setQuery).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    chartSettings: expect.objectContaining({
                        yAxis: [
                            expect.objectContaining({
                                column: 'value',
                                settings: expect.objectContaining({
                                    display: expect.objectContaining({
                                        displayType: 'area',
                                    }),
                                }),
                            }),
                        ],
                    }),
                })
            )
        )
    })
})
