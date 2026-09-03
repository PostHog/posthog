import '@testing-library/jest-dom'

import { cleanup, render, renderHook, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { createElement } from 'react'

import { LemonMenuItems, LemonMenuSection } from 'lib/lemon-ui/LemonMenu'

import { DataVisualizationNode, FunnelsQuery, InsightVizNode, Node, NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { sqlQueryForVisualizationPicker, useDashboardVisualizationOptions } from './dashboardVisualizationOptions'

type DashboardVisualizationOptionsProps = Parameters<typeof useDashboardVisualizationOptions>[0]

function displayOptionsElement(items: LemonMenuItems): JSX.Element {
    const section = items.find((item): item is LemonMenuSection => !!item && 'title' in item && item.key === 'display')
    expect(section).not.toBeUndefined()

    const item = section?.items[0]
    expect(item && typeof item.label).toBe('function')

    return (item as { label: () => JSX.Element }).label()
}

function chartTypeElement(items: LemonMenuItems): JSX.Element {
    const section = items.find(
        (item): item is LemonMenuSection => !!item && 'title' in item && item.title === 'Chart type'
    )
    expect(section).not.toBeUndefined()

    const item = section?.items[0]
    expect(item && typeof item.label).toBe('function')

    return (item as { label: () => JSX.Element }).label()
}

describe('dashboardVisualizationOptions', () => {
    const sqlQuery = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as DataVisualizationNode

    const trendsQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [] },
    } as unknown as InsightVizNode

    const stickinessQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.StickinessQuery, series: [] },
    } as unknown as InsightVizNode

    const retentionQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.RetentionQuery, retentionFilter: {} },
    } as unknown as InsightVizNode

    const funnelsQuery = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.FunnelsQuery, series: [] } as FunnelsQuery,
    } as InsightVizNode

    const persistence = {
        saving: null,
        version: 0,
        persistChartType: jest.fn(),
        persistDisplayOptions: jest.fn(),
    } as const

    afterEach(() => {
        cleanup()
    })

    describe('sqlQueryForVisualizationPicker', () => {
        it.each([
            { label: 'SQL insight gets the picker', query: sqlQuery as Node, canPersist: true, expected: sqlQuery },
            {
                label: 'a trends insight gets nothing, since its chart type carries query side effects',
                query: trendsQuery as Node,
                canPersist: true,
                expected: null,
            },
            {
                label: 'a non-SQL data visualization gets nothing',
                query: {
                    kind: NodeKind.DataVisualizationNode,
                    source: { kind: NodeKind.EventsQuery },
                } as unknown as DataVisualizationNode,
                canPersist: true,
                expected: null,
            },
            {
                label: 'no picker when the change cannot be saved, so a viewer never gets a control that no-ops',
                query: sqlQuery as Node,
                canPersist: false,
                expected: null,
            },
            { label: 'no picker without a query', query: null, canPersist: true, expected: null },
        ])('$label', ({ query, canPersist, expected }) => {
            expect(sqlQueryForVisualizationPicker(query, canPersist)).toBe(expected)
        })
    })

    describe('product analytics chart controls', () => {
        it.each([
            { label: 'Trends', query: trendsQuery, canPersist: true, expected: true },
            { label: 'Stickiness', query: stickinessQuery, canPersist: true, expected: true },
            { label: 'Retention', query: retentionQuery, canPersist: true, expected: true },
            { label: 'Funnels', query: funnelsQuery, canPersist: true, expected: false },
            { label: 'read-only Trends', query: trendsQuery, canPersist: false, expected: false },
        ])('shows the editor picker for $label: $expected', ({ query, canPersist, expected }) => {
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    query,
                    insightData: {},
                    persistence: canPersist ? persistence : undefined,
                })
            )

            const hasChartTypeSection = result.current.some(
                (item) => !!item && 'title' in item && item.title === 'Chart type'
            )
            expect(hasChartTypeSection).toBe(expected)
        })

        it('shows when product analytics display changes are being saved', () => {
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    query: trendsQuery,
                    insightData: {},
                    persistence,
                    savingDisplayOptions: true,
                })
            )
            const section = result.current.find(
                (item): item is LemonMenuSection => !!item && 'title' in item && item.title !== undefined
            )

            render(createElement('div', null, section?.title))

            expect(screen.getByRole('status')).toHaveTextContent('Saving')
        })
    })

    describe('SQL display controls', () => {
        const insightData = {
            columns: ['day', 'total'],
            types: [
                ['day', 'DateTime'],
                ['total', 'UInt64'],
            ],
            result: [
                ['2026-08-30', 12],
                ['2026-08-31', 15],
            ],
        }

        const lineQuery = {
            ...sqlQuery,
            display: ChartDisplayType.ActionsLineGraph,
            chartSettings: { xAxis: { column: 'day' }, yAxis: [{ column: 'total' }] },
        } as DataVisualizationNode

        const baseProps: DashboardVisualizationOptionsProps = {
            query: lineQuery,
            insightData,
            persistence: {
                saving: null,
                version: 0,
                persistChartType: jest.fn(),
                persistDisplayOptions: jest.fn(),
            },
        }

        beforeEach(() => {
            initKeaTests()
        })

        it('persists the chart type selected through the editor control', async () => {
            const persistChartType = jest.fn()
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    ...baseProps,
                    persistence: { ...baseProps.persistence!, persistChartType },
                })
            )
            const { container } = render(chartTypeElement(result.current))

            await userEvent.click(
                container.querySelector('[data-attr="dashboard-insight-visualization-picker"]') as HTMLElement
            )
            const matches = screen.getAllByText('Bar chart')
            await userEvent.click(matches[matches.length - 1])

            expect(persistChartType).toHaveBeenCalledWith(ChartDisplayType.ActionsBar)
        })

        it('restores the saved chart type after a failed save', async () => {
            const { result, rerender } = renderHook(
                (props: DashboardVisualizationOptionsProps) => useDashboardVisualizationOptions(props),
                { initialProps: baseProps }
            )
            const view = render(chartTypeElement(result.current))

            await userEvent.click(
                view.container.querySelector('[data-attr="dashboard-insight-visualization-picker"]') as HTMLElement
            )
            const matches = screen.getAllByText('Bar chart')
            await userEvent.click(matches[matches.length - 1])
            expect(
                view.container.querySelector('[data-attr="dashboard-insight-visualization-picker"]')
            ).toHaveTextContent('Bar chart')

            rerender({
                ...baseProps,
                persistence: { ...baseProps.persistence!, version: 1 },
            })
            view.rerender(chartTypeElement(result.current))

            expect(
                view.container.querySelector('[data-attr="dashboard-insight-visualization-picker"]')
            ).toHaveTextContent('Line chart')
        })

        it('reloads the available controls when the SQL chart type changes', async () => {
            const { result, rerender } = renderHook(
                (props: DashboardVisualizationOptionsProps) => useDashboardVisualizationOptions(props),
                { initialProps: baseProps }
            )
            const view = render(displayOptionsElement(result.current))

            expect(await screen.findByText('Right Y-axis')).toBeInTheDocument()
            expect(screen.getByText('Goals')).toBeInTheDocument()

            rerender({
                ...baseProps,
                query: {
                    ...lineQuery,
                    display: ChartDisplayType.ActionsPie,
                } as DataVisualizationNode,
            })
            view.rerender(displayOptionsElement(result.current))

            expect(await screen.findByText('Show on slices')).toBeInTheDocument()
            expect(screen.queryByText('Right Y-axis')).not.toBeInTheDocument()
            expect(screen.queryByText('Goals')).not.toBeInTheDocument()
        })

        it('routes display setting changes through SQL-safe persistence', async () => {
            const persistSqlDisplayOptions = jest.fn()
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    ...baseProps,
                    persistence: { ...baseProps.persistence!, persistDisplayOptions: persistSqlDisplayOptions },
                })
            )
            render(displayOptionsElement(result.current))

            const showLegend = await screen.findByLabelText('Show legend')
            expect(persistSqlDisplayOptions).not.toHaveBeenCalled()

            await userEvent.click(showLegend)

            await waitFor(() => {
                expect(persistSqlDisplayOptions).toHaveBeenCalledWith(
                    expect.objectContaining({
                        chartSettings: expect.objectContaining({ showLegend: true }),
                    })
                )
            })
        })

        it('waits for result columns before mounting display controls', async () => {
            const { result, rerender } = renderHook(
                (props: DashboardVisualizationOptionsProps) => useDashboardVisualizationOptions(props),
                {
                    initialProps: {
                        ...baseProps,
                        insightData: {},
                        loading: true,
                    },
                }
            )
            const view = render(displayOptionsElement(result.current))

            expect(screen.getByRole('status')).toHaveTextContent('Loading display options')
            expect(screen.queryByLabelText('Show legend')).not.toBeInTheDocument()

            rerender({ ...baseProps, loading: false })
            view.rerender(displayOptionsElement(result.current))

            expect(await screen.findByLabelText('Show legend')).toBeInTheDocument()
        })

        it('combines rapid setting changes across saving-state rerenders', async () => {
            const persistSqlDisplayOptions = jest.fn()
            const { result, rerender } = renderHook(
                (props: DashboardVisualizationOptionsProps) => useDashboardVisualizationOptions(props),
                {
                    initialProps: {
                        ...baseProps,
                        persistence: { ...baseProps.persistence!, persistDisplayOptions: persistSqlDisplayOptions },
                    },
                }
            )
            const view = render(displayOptionsElement(result.current))

            await userEvent.click(await screen.findByLabelText('Show legend'))
            const displayLabel = (
                result.current.find((item) => item && 'key' in item && item.key === 'display') as LemonMenuSection
            ).items[0]
            rerender({
                ...baseProps,
                persistence: {
                    ...baseProps.persistence!,
                    saving: 'display-options',
                    persistDisplayOptions: persistSqlDisplayOptions,
                },
            })
            const rerenderedDisplayLabel = (
                result.current.find((item) => item && 'key' in item && item.key === 'display') as LemonMenuSection
            ).items[0]
            expect(
                rerenderedDisplayLabel && 'label' in rerenderedDisplayLabel ? rerenderedDisplayLabel.label : null
            ).toBe(displayLabel && 'label' in displayLabel ? displayLabel.label : null)
            view.rerender(displayOptionsElement(result.current))
            expect(screen.getByLabelText('Show legend')).toBeChecked()
            await userEvent.click(screen.getByLabelText('Show annotations'))

            expect(persistSqlDisplayOptions).toHaveBeenLastCalledWith(
                expect.objectContaining({
                    chartSettings: expect.objectContaining({ showLegend: true, showAnnotations: true }),
                })
            )
        })

        it('shows when SQL visualization settings are being saved', () => {
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    ...baseProps,
                    persistence: { ...baseProps.persistence!, saving: 'display-options' },
                })
            )

            render(
                (result.current.find((item) => item && 'key' in item && item.key === 'display') as LemonMenuSection)
                    .title as JSX.Element
            )

            expect(screen.getByRole('status')).toHaveTextContent('Saving')
        })

        it('keeps display controls interactive while display options are being saved', () => {
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    ...baseProps,
                    persistence: { ...baseProps.persistence!, saving: 'display-options' },
                })
            )

            const { container } = render(displayOptionsElement(result.current))

            expect(container.firstChild).not.toHaveAttribute('inert')
        })

        it('makes display controls inert while the chart type is being saved', () => {
            const { result } = renderHook(() =>
                useDashboardVisualizationOptions({
                    ...baseProps,
                    persistence: { ...baseProps.persistence!, saving: 'chart-type' },
                })
            )

            const { container } = render(displayOptionsElement(result.current))

            expect(container.firstChild).toHaveAttribute('inert')
        })

        it('restores saved display settings after a failed save', async () => {
            const { result, rerender } = renderHook(
                (props: DashboardVisualizationOptionsProps) => useDashboardVisualizationOptions(props),
                { initialProps: baseProps }
            )
            const view = render(displayOptionsElement(result.current))

            await userEvent.click(await screen.findByLabelText('Show legend'))
            expect(screen.getByLabelText('Show legend')).toBeChecked()

            rerender({
                ...baseProps,
                persistence: { ...baseProps.persistence!, version: 1 },
            })
            view.rerender(displayOptionsElement(result.current))

            expect(await screen.findByLabelText('Show legend')).not.toBeChecked()
        })
    })
})
