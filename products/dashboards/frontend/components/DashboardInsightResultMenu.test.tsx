import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { consumePersonsModalClick } from 'lib/components/ResultMenu/personsModalCapture'
import { openPersonsModal, OpenPersonsModalProps } from 'scenes/trends/persons-modal/PersonsModal'

import { NodeKind } from '~/queries/schema/schema-general'
import { insightOnDashboard, tileFromInsight } from '~/scenes/dashboard/dashboardLogic.testHelpers'
import { initKeaTests } from '~/test/init'
import { BaseMathType, GroupMathType } from '~/types'

import { dashboardResultFilterLogic } from '../dashboardResultFilterLogic'
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
        expect(screen.getByText('Explore in new insight')).toBeInTheDocument()
        const rows = screen.getByText('View underlying rows')
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

it('filters a normal insight from the center link and clears on the same datapoint', () => {
    const request: OpenPersonsModalProps = {
        title: 'US',
        query: {
            kind: NodeKind.InsightActorsQuery,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdownFilter: { breakdown: 'country', breakdown_type: 'event' },
            },
            day: '2026-01-02',
            breakdown: ['US'],
        },
    }
    const insight = insightOnDashboard(1, [1])
    const logic = dashboardResultFilterLogic({ dashboardId: 1, tiles: [tileFromInsight(insight, 1)] })
    const unmount = logic.mount()
    try {
        render(
            <DashboardInsightResultMenu insight={insight} dashboardId={1} tileId={1}>
                <button onClick={() => openPersonsModal(request)}>Chart point</button>
            </DashboardInsightResultMenu>
        )
        fireEvent.click(screen.getByText('Chart point'))
        const center = screen.getByText('Filter dashboard by this result').closest('a')!
        expect(center.href).toContain('insight_filter=')
        fireEvent.click(center)
        expect(logic.values.selection?.query.source).toMatchObject({ day: '2026-01-02', breakdown: 'US' })
        fireEvent.click(screen.getByText('Chart point'))
        expect(logic.values.selection).toBeNull()
        expect(openedModal).not.toHaveBeenCalled()
    } finally {
        unmount()
    }
})
