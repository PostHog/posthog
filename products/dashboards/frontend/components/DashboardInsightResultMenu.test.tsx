import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { getContext } from 'kea'

import api from 'lib/api'
import { consumePersonsModalClick } from 'lib/components/ResultMenu/personsModalCapture'
import { openPersonsModal, OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'

import * as queryRunner from '~/queries/query'
import { BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind, ActorsQueryResponse, DataVisualizationNode, HogQLQuery } from '~/queries/schema/schema-general'
import { insightOnDashboard } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { BaseMathType, ChartDisplayType, GroupMathType } from '~/types'

import { DashboardInsightResultMenu } from './DashboardInsightResultMenu'

const openedModal = jest.fn()
jest.mock('scenes/trends/persons-modal/PersonsModal', () => ({
    openPersonsModal: (props: OpenPersonsModalProps): void => {
        if (!consumePersonsModalClick(props)) {
            openedModal(props)
        }
    },
}))

// Every dashboard tile renders the menu trigger, so a closed menu must not mount its result logic.
const resultLogicMounted = (): boolean =>
    Object.keys(getContext().mount.mounted).some((path) => path.includes('dashboardInsightResultMenuLogic'))

afterEach(() => {
    cleanup()
    jest.restoreAllMocks()
})
beforeEach(() => {
    initKeaTests()
    openedModal.mockClear()
    jest.spyOn(api, 'cancelQuery').mockResolvedValue()
    jest.spyOn(queryRunner, 'performQuery').mockResolvedValue({
        hogql: "SELECT id FROM persons WHERE properties.country = 'US'",
        results: [[{ id: 'person-selected' }, [{ session_id: 'session-selected' }]]],
    })
})

describe('dashboard result menu', () => {
    it('loads lifecycle people and SQL without requesting unsupported recordings', async () => {
        const request: OpenPersonsModalProps = {
            title: 'Resurrecting users',
            query: {
                kind: NodeKind.InsightActorsQuery,
                source: {
                    kind: NodeKind.LifecycleQuery,
                    series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                },
                day: '2026-01-02',
                status: 'resurrecting',
                includeRecordings: true,
            },
            additionalSelect: {},
        }
        render(
            <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                <button onClick={() => openPersonsModal(request)}>Lifecycle point</button>
            </DashboardInsightResultMenu>
        )
        expect(resultLogicMounted()).toBe(false)
        fireEvent.contextMenu(screen.getByText('Lifecycle point'))
        await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
        expect(resultLogicMounted()).toBe(true)
        expect(screen.queryByText('View recordings')).not.toBeInTheDocument()
        expect(queryRunner.performQuery).toHaveBeenCalledWith(
            expect.objectContaining({ source: request.query, select: ['actor'] }),
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
            undefined,
            expect.any(String)
        )
        fireEvent.click(screen.getByText('View people'))
        expect(openedModal).toHaveBeenCalledWith(request)
    })

    it('opens BI query snapshots in the SQL editor with their source intact', () => {
        const source: HogQLQuery = {
            kind: NodeKind.HogQLQuery,
            query: 'SELECT count() FROM orders',
            connectionId: 'demo-connection',
        }
        const query: BIVisualizationNode = {
            kind: NodeKind.BIVisualizationNode,
            source,
            config: {
                source: null,
                querySnapshot: source,
                chartType: ChartDisplayType.ActionsBar,
                rows: [],
                columns: [],
                values: [],
                filters: [],
                limit: 1000,
            },
        }
        render(
            <DashboardInsightResultMenu insight={{ ...insightOnDashboard(1, [1]), query }}>
                <div>Snapshot chart</div>
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('Snapshot chart'))
        for (const label of ['View underlying rows', 'Open in SQL editor']) {
            const link = screen.getByText(label).closest('a')!
            expect(JSON.parse(new URL(link.href).searchParams.get('open_query')!)).toEqual({
                kind: NodeKind.DataVisualizationNode,
                source,
                display: ChartDisplayType.ActionsTable,
            })
        }
        expect(queryRunner.performQuery).not.toHaveBeenCalled()
    })

    it('opens a SQL chart in the SQL editor with its chart display and its rows as a table', () => {
        const query: DataVisualizationNode = {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: 'SELECT day, count() FROM events GROUP BY day' },
            display: ChartDisplayType.ActionsLineGraph,
        }
        render(
            <DashboardInsightResultMenu insight={{ ...insightOnDashboard(1, [1]), query }}>
                <div>SQL chart</div>
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('SQL chart'))
        const openQuery = (label: string): unknown =>
            JSON.parse(new URL(screen.getByText(label).closest('a')!.href).searchParams.get('open_query')!)
        expect(openQuery('Open in SQL editor')).toEqual(query)
        expect(openQuery('View underlying rows')).toEqual({ ...query, display: ChartDisplayType.ActionsTable })
    })

    it.each([undefined, 0] as const)(
        'defers the original datapoint drilldown with all user/group filters intact (group=%s)',
        async (groupIndex) => {
            const request: OpenPersonsModalProps = {
                title: 'Selected country',
                query: {
                    kind: NodeKind.InsightActorsQuery,
                    source: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                kind: NodeKind.EventsNode,
                                event: '$pageview',
                                math: groupIndex === undefined ? BaseMathType.UniqueUsers : GroupMathType.UniqueGroup,
                                ...(groupIndex !== undefined ? { math_group_type_index: groupIndex } : {}),
                            },
                        ],
                        dateRange: { date_from: '-7d' },
                        breakdownFilter: { breakdown: '$geoip_country_code', breakdown_type: 'person' },
                    },
                    series: 0,
                    day: '2026-01-02',
                    breakdown: ['US'],
                },
                additionalSelect: { matched_recordings: 'matched_recordings' },
                orderBy: ['actor_id DESC'],
            }
            render(
                <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                    <button onClick={() => openPersonsModal(request)}>Chart point</button>
                </DashboardInsightResultMenu>
            )
            expect(fireEvent.contextMenu(screen.getByText('Chart point'))).toBe(false)
            expect(openedModal).not.toHaveBeenCalled()
            expect(screen.getByText('Selected country')).toBeInTheDocument()
            expect(screen.queryByText('Explore in new insight')).not.toBeInTheDocument()
            expect(screen.queryByText('Filter dashboard by this result')).not.toBeInTheDocument()
            expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
                'View people',
                'View recordings',
                'Open in SQL editor',
            ])
            fireEvent.click(screen.getByText('Chart point'))
            expect(screen.queryByRole('menu')).not.toBeInTheDocument()
            expect(openedModal).toHaveBeenCalledWith(request)
            openedModal.mockClear()
            fireEvent.contextMenu(screen.getByText('Chart point'))
            const rows = screen.getByText('View people')
            const href = rows.closest('a')!.getAttribute('href')!
            expect(decodeURIComponent(href)).toContain('"kind":"ActorsQuery"')
            expect(decodeURIComponent(href)).toContain('"day":"2026-01-02"')
            expect(decodeURIComponent(href)).toContain('"breakdown":["US"]')
            await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
            const sqlHref = screen.getByText('Open in SQL editor').closest('a')!.getAttribute('href')!
            expect(new URL(sqlHref, 'https://example.com').searchParams.get('open_query')).toBe(
                "SELECT id FROM persons WHERE properties.country = 'US'"
            )
            const replayHref = screen.getByText('View recordings').closest('a')!.getAttribute('href')!
            expect(decodeURIComponent(replayHref)).toContain('"session_ids":["session-selected"]')
            expect(queryRunner.performQuery).toHaveBeenCalledWith(
                expect.objectContaining({
                    kind: NodeKind.ActorsQuery,
                    source: request.query,
                    select: ['actor', 'matched_recordings'],
                    orderBy: request.orderBy,
                }),
                expect.objectContaining({ signal: expect.any(AbortSignal) }),
                undefined,
                expect.any(String)
            )
            fireEvent.click(rows)
            expect(openedModal).toHaveBeenCalledTimes(1)
            expect(openedModal).toHaveBeenCalledWith(request)
            expect(screen.queryByRole('menu')).not.toBeInTheDocument()
        }
    )
    it('resolves funnel rows without exposing unrelated recordings when no sessions match', async () => {
        jest.mocked(queryRunner.performQuery).mockResolvedValue({ hogql: 'SELECT id FROM persons', results: [] })
        const request: OpenPersonsModalProps = {
            title: 'Funnel step',
            query: {
                kind: NodeKind.FunnelsActorsQuery,
                source: { kind: NodeKind.FunnelsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
                funnelStep: 1,
                funnelStepBreakdown: ['US'],
            },
            additionalSelect: { matched_recordings: 'matched_recordings' },
        }
        render(
            <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                <button onClick={() => openPersonsModal(request)}>Funnel point</button>
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('Funnel point'))
        await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
        expect(queryRunner.performQuery).toHaveBeenCalledWith(
            expect.objectContaining({ source: request.query }),
            expect.objectContaining({ signal: expect.any(AbortSignal) }),
            undefined,
            expect.any(String)
        )
        expect(screen.getByText('View recordings').closest('a')).toBeNull()
    })

    it('discards an older result after selecting another point and lets failed requests retry', async () => {
        let resolveFirst!: (response: ActorsQueryResponse) => void
        jest.mocked(queryRunner.performQuery)
            .mockImplementationOnce(
                () =>
                    new Promise<ActorsQueryResponse>((resolve) => {
                        resolveFirst = resolve
                    })
            )
            .mockRejectedValueOnce(new Error('Query failed'))
            .mockResolvedValueOnce({ hogql: 'SELECT 2', results: [] })
        const point = (day: string): OpenPersonsModalProps => ({
            title: day,
            query: {
                kind: NodeKind.InsightActorsQuery,
                source: { kind: NodeKind.TrendsQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
                day,
            },
        })
        render(
            <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                <button onClick={() => openPersonsModal(point('2026-01-01'))}>First point</button>
                <button onClick={() => openPersonsModal(point('2026-01-02'))}>Second point</button>
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('First point'))
        await waitFor(() => expect(queryRunner.performQuery).toHaveBeenCalledTimes(1))
        fireEvent.contextMenu(screen.getByText('Second point'))
        await waitFor(() => expect(queryRunner.performQuery).toHaveBeenCalledTimes(2))
        const firstCall = jest.mocked(queryRunner.performQuery).mock.calls[0]
        const secondCall = jest.mocked(queryRunner.performQuery).mock.calls[1]
        expect(firstCall[1]?.signal?.aborted).toBe(true)
        expect(api.cancelQuery).toHaveBeenCalledWith(firstCall[3])
        expect(secondCall[3]).not.toBe(firstCall[3])
        expect(secondCall[1]?.signal?.aborted).toBe(false)
        await act(async () => resolveFirst({ hogql: 'SELECT 1', results: [] } as unknown as ActorsQueryResponse))
        expect(screen.getByText('Open in SQL editor').closest('a')).toBeNull()
        fireEvent.contextMenu(screen.getByText('Second point'))
        await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
        const link = screen.getByText('Open in SQL editor').closest('a')!
        expect(new URL(link.href).searchParams.get('open_query')).toBe('SELECT 2')
    })

    it.each(['dismiss', 'unmount', 'complete'] as const)('cancels only pending queries on %s', async (finish) => {
        let resolveQuery!: (response: ActorsQueryResponse) => void
        jest.mocked(queryRunner.performQuery).mockImplementationOnce(
            (_, options) =>
                new Promise<ActorsQueryResponse>((resolve, reject) => {
                    resolveQuery = resolve
                    options?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
                })
        )
        const { unmount } = render(
            <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                <button
                    onClick={() =>
                        openPersonsModal({
                            title: 'Selected people',
                            query: {
                                kind: NodeKind.InsightActorsQuery,
                                source: { kind: NodeKind.TrendsQuery, series: [] },
                            },
                        })
                    }
                >
                    Chart point
                </button>
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('Chart point'))
        await waitFor(() => expect(queryRunner.performQuery).toHaveBeenCalledTimes(1))
        const call = jest.mocked(queryRunner.performQuery).mock.calls[0]
        if (finish === 'complete') {
            await act(async () => resolveQuery({ hogql: 'SELECT 1', results: [] } as unknown as ActorsQueryResponse))
            await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
        }
        if (finish === 'dismiss') {
            fireEvent.keyDown(screen.getByRole('menu'), { key: 'Escape' })
        } else {
            unmount()
        }
        await waitFor(() => expect(screen.queryByRole('menu')).not.toBeInTheDocument())
        expect(call[1]?.signal?.aborted).toBe(finish !== 'complete')
        if (finish === 'complete') {
            expect(api.cancelQuery).not.toHaveBeenCalled()
        } else {
            expect(api.cancelQuery).toHaveBeenCalledTimes(1)
            expect(api.cancelQuery).toHaveBeenCalledWith(call[3])
        }
    })

    it.each([
        [
            'a context menu that a child handles',
            (onClick: () => void) => (
                <div onClick={onClick} onContextMenu={(event) => event.preventDefault()}>
                    Target
                </div>
            ),
        ],
        [
            'a legend row',
            (onClick: () => void) => (
                <div data-hog-charts-legend="">
                    <button onClick={onClick}>Target</button>
                </div>
            ),
        ],
    ])('leaves %s alone', (_, renderTarget) => {
        const onClick = jest.fn()
        render(
            <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                {renderTarget(onClick)}
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('Target'))
        expect(onClick).not.toHaveBeenCalled()
        expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    })

    it('does not offer recordings for a drilldown without recording support', () => {
        const request: OpenPersonsModalProps = {
            title: 'Selected people',
            query: {
                kind: NodeKind.InsightActorsQuery,
                source: { kind: NodeKind.StickinessQuery, series: [{ kind: NodeKind.EventsNode, event: '$pageview' }] },
            },
        }
        render(
            <DashboardInsightResultMenu insight={insightOnDashboard(1, [1])}>
                <button onClick={() => openPersonsModal(request)}>Chart point</button>
            </DashboardInsightResultMenu>
        )
        fireEvent.contextMenu(screen.getByText('Chart point'))
        expect(screen.queryByText('View recordings')).not.toBeInTheDocument()
        fireEvent.scroll(window)
        expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    })
})
