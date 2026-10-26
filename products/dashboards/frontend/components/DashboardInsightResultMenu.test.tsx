import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { consumePersonsModalClick } from 'lib/components/ResultMenu/personsModalCapture'
import { openPersonsModal, OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'

import { NodeKind } from '~/queries/schema/schema-general'
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

afterEach(cleanup)
beforeEach(() => {
    initKeaTests()
    openedModal.mockClear()
})

describe('dashboard result menu', () => {
    it.each([undefined, 0] as const)(
        'defers the original datapoint drilldown with all user/group filters intact (group=%s)',
        (groupIndex) => {
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
            const sqlHref = screen.getByText('Open in SQL editor').closest('a')!.getAttribute('href')!
            const query = new URL(sqlHref, 'https://example.com').searchParams.get('open_query')!
            expect(JSON.parse(query).source).toMatchObject({
                kind: NodeKind.ActorsQuery,
                source: request.query,
                select: ['actor', 'matched_recordings'],
                orderBy: request.orderBy,
            })
            fireEvent.click(rows)
            expect(openedModal).toHaveBeenCalledTimes(1)
            expect(openedModal).toHaveBeenCalledWith(request)
            expect(screen.queryByRole('menu')).not.toBeInTheDocument()
        }
    )
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
