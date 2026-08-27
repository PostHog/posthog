import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { DataVisualizationLogicProps, dataVisualizationLogic } from '../dataVisualizationLogic'
import { displayLogic } from '../displayLogic'
import { DisplayTab } from './DisplayTab'

describe('DisplayTab', () => {
    afterEach(() => {
        cleanup()
    })

    it('labels Y-axis tick toggles explicitly', async () => {
        initKeaTests()

        const key = 'display-tab-axis-tick-label-test'
        const query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select company_size, accounts, revenue from numbers(2)',
            },
            display: ChartDisplayType.ActionsBar,
            chartSettings: {},
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            setQuery: jest.fn(),
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        const user = userEvent.setup()

        await user.click(await screen.findByText('Left Y-axis'))
        await user.click(screen.getByText('Right Y-axis'))

        expect(screen.getByText('Show X-axis tick labels')).toBeInTheDocument()
        expect(screen.getAllByText('Show tick labels')).toHaveLength(2)
        expect(screen.queryByText('Show X-axis labels')).not.toBeInTheDocument()
        expect(screen.queryByText('Show labels')).not.toBeInTheDocument()
    })

    it('persists chart axis labels without dropping existing axis settings', async () => {
        initKeaTests()

        const setQuery = jest.fn()
        const key = 'display-tab-axis-label-test'
        let query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select company_size, accounts, revenue from numbers(2)',
            },
            display: ChartDisplayType.ActionsBar,
            chartSettings: {
                leftYAxisSettings: {
                    scale: 'logarithmic',
                },
                rightYAxisSettings: {
                    showTicks: false,
                },
            },
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            setQuery: (setter) => {
                query = setter(query)
                setQuery(query)
            },
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        const user = userEvent.setup()

        await user.type(await screen.findByPlaceholderText('X-axis label'), 'Company size')

        await user.click(screen.getByText('Left Y-axis'))
        await user.type(await screen.findByPlaceholderText('Left Y-axis label'), 'Accounts')

        await user.click(screen.getByText('Right Y-axis'))
        await user.type(await screen.findByPlaceholderText('Right Y-axis label'), 'Revenue')

        await waitFor(() => {
            expect(setQuery).toHaveBeenCalled()
            expect(query.chartSettings).toEqual(
                expect.objectContaining({
                    xAxisLabel: 'Company size',
                    leftYAxisSettings: expect.objectContaining({
                        label: 'Accounts',
                        scale: 'logarithmic',
                    }),
                    rightYAxisSettings: expect.objectContaining({
                        label: 'Revenue',
                        showTicks: false,
                    }),
                })
            )
        })
    })
    it('offers box plot settings and hides unsupported controls', async () => {
        initKeaTests()

        const key = 'display-tab-box-plot-test'
        let query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select * from summaries',
            },
            display: ChartDisplayType.BoxPlot,
            chartSettings: { boxPlot: { excludeOutliers: true } },
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            setQuery: (setter) => {
                query = setter(query)
            },
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        const user = userEvent.setup()

        expect(await screen.findByText('Y-axis')).toBeInTheDocument()
        expect(screen.queryByText('Right Y-axis')).not.toBeInTheDocument()
        expect(screen.queryByText('Goals')).not.toBeInTheDocument()
        expect(screen.queryByText('Show total row')).not.toBeInTheDocument()

        await user.click(screen.getByText('Exclude outliers'))
        await user.click(screen.getByText('Y-axis'))
        expect(screen.queryByText('Begin at zero')).not.toBeInTheDocument()

        await waitFor(() => expect(query.chartSettings?.boxPlot?.excludeOutliers).toBe(false))
    })

    it('offers scatter axis settings and drops the panels a scatter has no support for', async () => {
        initKeaTests()

        const key = 'display-tab-scatter-test'
        let query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select session_duration, revenue from numbers(2)',
            },
            display: ChartDisplayType.ScatterPlot,
            chartSettings: {},
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            setQuery: (setter) => {
                query = setter(query)
            },
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        const user = userEvent.setup()

        // One gutter per axis, and quill's scatter takes no goal lines.
        expect(await screen.findByText('X-axis')).toBeInTheDocument()
        expect(screen.getByText('Y-axis')).toBeInTheDocument()
        expect(screen.queryByText('Right Y-axis')).not.toBeInTheDocument()
        expect(screen.queryByText('Goals')).not.toBeInTheDocument()

        await user.click(screen.getByText('Show line of best fit'))

        await user.click(screen.getByText('X-axis'))
        await user.click(await screen.findByText('Begin at zero'))

        // Both live under `scatter`, so the second write must merge into the first rather than replace it.
        await waitFor(() => {
            expect(query.chartSettings).toEqual(
                expect.objectContaining({
                    scatter: expect.objectContaining({ showBestFit: true, xStartAtZero: true }),
                })
            )
        })
    })
})
