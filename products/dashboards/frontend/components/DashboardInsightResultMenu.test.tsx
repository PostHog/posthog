import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { consumePersonsModalClick } from 'lib/components/ResultMenu/personsModalCapture'
import { openPersonsModal, OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'

import * as queryRunner from '~/queries/query'
import { NodeKind, ActorsQueryResponse } from '~/queries/schema/schema-general'
import { insightOnDashboard } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { BaseMathType, GroupMathType } from '~/types'

import { DashboardInsightResultMenu } from './DashboardInsightResultMenu'

const openedModal = jest.fn()
jest.mock('scenes/trends/persons-modal/PersonsModal', () => ({
    openPersonsModal: (props: OpenPersonsModalProps): void => {
        if (!consumePersonsModalClick(props)) {
            openedModal(props)
        }
    },
}))

afterEach(() => {
    cleanup()
    jest.restoreAllMocks()
})
beforeEach(() => {
    initKeaTests()
    openedModal.mockClear()
    jest.spyOn(queryRunner, 'performQuery').mockResolvedValue({
        hogql: "SELECT id FROM persons WHERE properties.country = 'US'",
        results: [[{ id: 'person-selected' }, [{ session_id: 'session-selected' }]]],
    })
})

describe('dashboard result menu', () => {
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
            fireEvent.click(screen.getByText('Chart point'))
            expect(openedModal).not.toHaveBeenCalled()
            expect(screen.getByText('Selected country')).toBeInTheDocument()
            expect(screen.queryByText('Explore in new insight')).not.toBeInTheDocument()
            expect(screen.queryByText('Filter dashboard by this result')).not.toBeInTheDocument()
            expect(screen.getAllByRole('menuitem').map((item) => item.textContent)).toEqual([
                'View people',
                'Open in SQL editor',
                'View recordings',
            ])
            fireEvent.click(screen.getByText('Chart point'))
            expect(screen.queryByRole('menu')).not.toBeInTheDocument()
            fireEvent.click(screen.getByText('Chart point'))
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
                })
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
        fireEvent.click(screen.getByText('Funnel point'))
        await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
        expect(queryRunner.performQuery).toHaveBeenCalledWith(expect.objectContaining({ source: request.query }))
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
        fireEvent.click(screen.getByText('First point'))
        await waitFor(() => expect(queryRunner.performQuery).toHaveBeenCalledTimes(1))
        fireEvent.click(screen.getByText('Second point'))
        await waitFor(() => expect(queryRunner.performQuery).toHaveBeenCalledTimes(2))
        await act(async () => resolveFirst({ hogql: 'SELECT 1', results: [] } as unknown as ActorsQueryResponse))
        expect(screen.getByText('Open in SQL editor').closest('a')).toBeNull()
        fireEvent.click(screen.getByText('Second point'))
        fireEvent.click(screen.getByText('Second point'))
        await waitFor(() => expect(screen.getByText('Open in SQL editor').closest('a')).not.toBeNull())
        const link = screen.getByText('Open in SQL editor').closest('a')!
        expect(new URL(link.href).searchParams.get('open_query')).toBe('SELECT 2')
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
        fireEvent.click(screen.getByText('Chart point'))
        expect(screen.queryByText('View recordings')).not.toBeInTheDocument()
        fireEvent.scroll(window)
        expect(screen.queryByRole('menu')).not.toBeInTheDocument()
    })
})
