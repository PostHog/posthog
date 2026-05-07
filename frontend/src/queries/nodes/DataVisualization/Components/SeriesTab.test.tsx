import '@testing-library/jest-dom'

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { dataNodeLogic } from '../../DataNode/dataNodeLogic'
import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { YSeriesDisplayTab, YSeriesFormattingTab } from './SeriesTab'
import { YSeriesLogicProps } from './ySeriesLogic'

describe('SeriesTab', () => {
    it('persists table column formatting changes immediately', async () => {
        initKeaTests()

        const setQuery = jest.fn()
        const query: DataVisualizationNode = {
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
        const query: DataVisualizationNode = {
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
