import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BindLogic } from 'kea'

import { VisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
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
        const query: VisualizationNode = {
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

        await user.click(await screen.findByText('X-axis'))
        await user.click(await screen.findByText('Left Y-axis'))
        await user.click(await screen.findByText('Right Y-axis'))

        expect(screen.getAllByText('Show tick labels')).toHaveLength(3)
        expect(screen.queryByText('Show X-axis labels')).not.toBeInTheDocument()
        expect(screen.queryByText('Show labels')).not.toBeInTheDocument()
    })

    it('keeps annotations off by default and persists the toggle', async () => {
        initKeaTests()

        const key = 'display-tab-annotations-test'
        let query: VisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select day, accounts from numbers(2)',
            },
            display: ChartDisplayType.ActionsLineGraph,
            chartSettings: { xAxis: { column: 'day' } },
        }

        const props: DataVisualizationLogicProps = {
            key,
            query,
            dataNodeCollectionId: key,
            cachedResults: {
                columns: ['day', 'accounts'],
                types: [
                    ['day', 'Date'],
                    ['accounts', 'UInt64'],
                ],
                results: [
                    ['2026-01-01', 1],
                    ['2026-01-02', 2],
                ],
                hogql: '',
                hasMore: false,
            } as HogQLQueryResponse,
            setQuery: (setter) => {
                query = setter(query)
            },
        }

        dataVisualizationLogic(props).mount()
        displayLogic({ key }).mount()

        const { container } = render(
            <BindLogic logic={dataVisualizationLogic} props={props}>
                <BindLogic logic={displayLogic} props={{ key }}>
                    <DisplayTab />
                </BindLogic>
            </BindLogic>
        )

        await screen.findByText('Annotations')
        const annotationsSelect = container.querySelector('[data-attr="data-visualization-show-annotations"]')
        expect(annotationsSelect).toHaveTextContent('None')

        await userEvent.click(annotationsSelect as HTMLElement)
        await userEvent.click(await screen.findByText('All'))

        await waitFor(() => {
            expect(query.chartSettings?.showAnnotations).toBe(true)
        })
    })

    it('persists chart axis labels without dropping existing axis settings', async () => {
        initKeaTests()

        const setQuery = jest.fn()
        const key = 'display-tab-axis-label-test'
        let query: VisualizationNode = {
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

        await user.click(await screen.findByText('X-axis'))
        await user.click(await screen.findByText('Left Y-axis'))
        await user.click(await screen.findByText('Right Y-axis'))
        const labelInput = (dataAttr: string): HTMLElement =>
            document.querySelector<HTMLElement>(`[data-attr="${dataAttr}"]`) as HTMLElement
        await user.type(labelInput('data-visualization-x-axis-label-input'), 'Company size')
        await user.tab()
        await user.type(labelInput('data-visualization-left-y-axis-label-input'), 'Accounts')
        await user.tab()
        await user.type(labelInput('data-visualization-right-y-axis-label-input'), 'Revenue')
        await user.tab()

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
        let query: VisualizationNode = {
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
        expect(screen.queryByText('Goal lines')).not.toBeInTheDocument()
        expect(screen.queryByText('Show total row')).not.toBeInTheDocument()
        expect(screen.queryByText('Annotations')).not.toBeInTheDocument()

        await user.click(screen.getByText('Exclude outliers'))
        await user.click(screen.getByText('Y-axis'))
        expect(screen.queryByText('Right Y-axis')).not.toBeInTheDocument()
        expect(screen.queryByText('Begin at zero')).not.toBeInTheDocument()

        await waitFor(() => expect(query.chartSettings?.boxPlot?.excludeOutliers).toBe(false))
    })

    it('offers only the metric settings for a metric and persists them', async () => {
        initKeaTests()

        const key = 'display-tab-metric-test'
        let query: VisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: {
                kind: NodeKind.HogQLQuery,
                query: 'select day, revenue from summaries',
            },
            display: ChartDisplayType.Metric,
            chartSettings: { metric: { summary: 'average' } },
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

        expect(await screen.findByText('Headline value')).toBeInTheDocument()
        expect(screen.queryByText('Show legend')).not.toBeInTheDocument()
        expect(screen.queryByText('X-axis')).not.toBeInTheDocument()
        expect(screen.queryByText('Goal lines')).not.toBeInTheDocument()

        await user.click(screen.getByText('Show change'))

        await waitFor(() => expect(query.chartSettings?.metric).toEqual({ summary: 'average', showChange: false }))
    })

    it('offers scatter axis settings and drops the panels a scatter has no support for', async () => {
        initKeaTests()

        const key = 'display-tab-scatter-test'
        let query: VisualizationNode = {
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

        await user.click(await screen.findByText('Lines'))
        await user.click(await screen.findByText('Show trend lines'))
        // Quill's scatter takes no goal lines.
        expect(screen.queryByText('Goal lines')).not.toBeInTheDocument()

        // One gutter per axis.
        expect(screen.getByText('Y-axis')).toBeInTheDocument()
        expect(screen.queryByText('Right Y-axis')).not.toBeInTheDocument()
        await user.click(screen.getByText('X-axis'))
        await user.click(screen.getByText('Begin at zero'))

        // Both live under `scatter`, so the second write must merge into the first rather than replace it.
        await waitFor(() => {
            expect(query.chartSettings).toEqual(
                expect.objectContaining({
                    scatter: expect.objectContaining({ showBestFit: true, xStartAtZero: true }),
                })
            )
        })
    })

    it.each([ChartDisplayType.ActionsPie, ChartDisplayType.ActionsDonut, ChartDisplayType.ActionsProportionBar])(
        'honors the legacy top-level showPieTotal when pie.showTotal is unset (%s)',
        async (display) => {
            initKeaTests()

            const key = `display-tab-legacy-show-total-test-${display}`
            const query: VisualizationNode = {
                kind: NodeKind.DataVisualizationNode,
                source: {
                    kind: NodeKind.HogQLQuery,
                    query: 'select label, total from numbers(2)',
                },
                display,
                chartSettings: { showPieTotal: false },
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

            const toggle = (await screen.findByText('Show total')).closest('div')?.querySelector('[role="switch"]')
            expect(toggle).toHaveAttribute('aria-checked', 'false')
        }
    )
})
