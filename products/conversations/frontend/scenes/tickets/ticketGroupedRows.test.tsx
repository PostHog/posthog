import { LemonTableColumns } from '@posthog/lemon-ui'

import { Ticket } from '../../types'
import {
    buildTicketGroupedRows,
    isTicketGroupHeaderRow,
    TicketListRow,
    withTicketGroupHeaderRows,
} from './ticketGroupedRows'

/** Grouping reads the SERVER-computed rank off the ticket — nothing here is
 *  re-derived from tags or filters. */
const ticket = (id: string, ticket_group_rank: number): Ticket => ({ id, ticket_group_rank }) as unknown as Ticket

const tagGroup = (label: string, ...tags: string[]): { label: string; filters: any[] } => ({
    label,
    filters: [{ type: 'ticket_tags', operator: 'any_of', value: tags }],
})

const triage = ticket('t', 0)
const churn = ticket('ch', 1)
const top20 = ticket('t20', 2)
const enterprise = ticket('e', 3)
const free = ticket('f', 4)
const community = ticket('co', 5)

// A six-tier fixture ladder — enough groups to exercise leading/inner/trailing
// gaps, independent of the example default ladder.
const GROUPS = [
    tagGroup('Triage', 'needs_triage'),
    tagGroup('Churn risk', 'churn_risk'),
    tagGroup('Top 20', 'top_20'),
    tagGroup('Enterprise', 'plan_enterprise'),
    tagGroup('Free plan', 'plan_free'),
    tagGroup('Community', 'community'),
]

const SINGLE_PAGE = {
    groups: GROUPS,
    desc: false,
    isFirstPage: true,
    isLastPage: true,
}

describe('buildTicketGroupedRows', () => {
    it('returns an empty list unchanged (empty state, no headers)', () => {
        expect(buildTicketGroupedRows([], SINGLE_PAGE)).toEqual([])
    })

    it('groups tickets under headers and marks provably-empty groups between them', () => {
        const rows = buildTicketGroupedRows([churn, enterprise], SINGLE_PAGE)
        expect(rows).toEqual([
            { ticketGroupHeader: 'Triage', empty: true },
            { ticketGroupHeader: 'Churn risk' },
            churn,
            { ticketGroupHeader: 'Top 20', empty: true },
            { ticketGroupHeader: 'Enterprise' },
            enterprise,
            { ticketGroupHeader: 'Free plan', empty: true },
            { ticketGroupHeader: 'Community', empty: true },
        ])
    })

    it('emits one header for a run of same-group tickets', () => {
        const rows = buildTicketGroupedRows([ticket('a', 4), ticket('b', 4)], SINGLE_PAGE)
        expect(rows.filter((r) => isTicketGroupHeaderRow(r) && !r.empty)).toHaveLength(1)
    })

    it('omits leading empties when not the first page, trailing when not the last', () => {
        const middlePage = buildTicketGroupedRows([enterprise], {
            ...SINGLE_PAGE,
            isFirstPage: false,
            isLastPage: false,
        })
        expect(middlePage).toEqual([{ ticketGroupHeader: 'Enterprise' }, enterprise])
    })

    it('reverses the ladder when sorted descending', () => {
        const rows = buildTicketGroupedRows([community, free], {
            ...SINGLE_PAGE,
            desc: true,
            isLastPage: false,
        })
        expect(rows[0]).toEqual({ ticketGroupHeader: 'Community' })
        expect(rows[1]).toEqual(community)
        expect(rows[2]).toEqual({ ticketGroupHeader: 'Free plan' })
        expect(rows[3]).toEqual(free)
        // not the last page → no trailing empties beyond Free plan
        expect(rows).toHaveLength(4)
    })

    it('marks inner gaps as empty on any page (adjacency proves emptiness)', () => {
        const rows = buildTicketGroupedRows([triage, top20], {
            ...SINGLE_PAGE,
            isFirstPage: false,
            isLastPage: false,
        })
        expect(rows).toEqual([
            { ticketGroupHeader: 'Triage' },
            triage,
            { ticketGroupHeader: 'Churn risk', empty: true },
            { ticketGroupHeader: 'Top 20' },
            top20,
        ])
    })

    it('stamps headers with server counts by group rank when provided', () => {
        const rows = buildTicketGroupedRows([churn, enterprise], {
            ...SINGLE_PAGE,
            counts: { '1': 12, '3': 4 },
        })
        expect(rows).toContainEqual({ ticketGroupHeader: 'Churn risk', count: 12 })
        expect(rows).toContainEqual({ ticketGroupHeader: 'Enterprise', count: 4 })
        // groups absent from the counts map are zero-matching
        expect(rows).toContainEqual({ ticketGroupHeader: 'Top 20', empty: true, count: 0 })
    })

    it('keeps counts keyed by original ladder rank when descending reverses the walk', () => {
        const rows = buildTicketGroupedRows([enterprise, churn], {
            ...SINGLE_PAGE,
            desc: true,
            counts: { '1': 12, '3': 4 },
        })
        // ranks are ladder positions (Churn risk = 1, Enterprise = 3) regardless of display order
        expect(rows).toContainEqual({ ticketGroupHeader: 'Enterprise', count: 4 })
        expect(rows).toContainEqual({ ticketGroupHeader: 'Churn risk', count: 12 })
        expect(rows).toContainEqual({ ticketGroupHeader: 'Community', empty: true, count: 0 })
        // descending: Enterprise renders before Churn risk
        const labels = rows.filter(isTicketGroupHeaderRow).map((r) => r.ticketGroupHeader)
        expect(labels.indexOf('Enterprise')).toBeLessThan(labels.indexOf('Churn risk'))
    })

    it('groups against a custom ladder', () => {
        const groups = [tagGroup('VIPs', 'vip'), tagGroup('Everyone else', 'plan_free')]
        const vip = ticket('v', 0)
        const other = ticket('o', 1)
        const rows = buildTicketGroupedRows([vip, other], { ...SINGLE_PAGE, groups })
        expect(rows).toEqual([{ ticketGroupHeader: 'VIPs' }, vip, { ticketGroupHeader: 'Everyone else' }, other])
    })

    it('falls back to the first group for a rank past the end of the ladder', () => {
        // Possible when the team edits its groups between the list request and
        // the render — index defensively rather than crashing.
        const groups = [tagGroup('VIPs', 'vip'), tagGroup('Everyone else', 'plan_free')]
        const stale = ticket('s', 9)
        expect(buildTicketGroupedRows([stale], { ...SINGLE_PAGE, groups })).toEqual([
            { ticketGroupHeader: 'VIPs' },
            stale,
            { ticketGroupHeader: 'Everyone else', empty: true },
        ])
    })

    it('does not mutate the caller-owned groups array when descending', () => {
        const groups = [tagGroup('VIPs', 'vip'), tagGroup('Everyone else', 'plan_free')]
        buildTicketGroupedRows([ticket('x', 1)], { ...SINGLE_PAGE, groups, desc: true })
        expect(groups.map((g) => g.label)).toEqual(['VIPs', 'Everyone else'])
    })
})

describe('withTicketGroupHeaderRows', () => {
    const columns: LemonTableColumns<Ticket> = [
        { key: 'one', title: 'One', width: 80, render: (_, t) => `one:${t.id}` },
        { key: 'two', title: 'Two', sorter: true, render: (_, t) => `two:${t.id}` },
        { key: 'three', title: 'Three', render: (_, t) => `three:${t.id}` },
    ]
    const wrapped = withTicketGroupHeaderRows(columns)
    const header: TicketListRow = { ticketGroupHeader: 'Enterprise' }

    it('renders the header label spanning every column in the first cell', () => {
        const cell = wrapped[0].render!(undefined, header, 0, 1) as { children: JSX.Element; props: object }
        expect(cell.props).toEqual({ colSpan: 3 })
        expect(JSON.stringify(cell.children)).toContain('Enterprise')
    })

    it('renders the zero-match note on empty group headers', () => {
        const emptyHeader: TicketListRow = { ticketGroupHeader: 'Top 20', empty: true }
        const cell = wrapped[0].render!(undefined, emptyHeader, 0, 1) as { children: JSX.Element }
        expect(JSON.stringify(cell.children)).toContain('zero tickets match current filters')
    })

    it('renders match counts on populated headers, with singular grammar for one', () => {
        const many: TicketListRow = { ticketGroupHeader: 'Enterprise', count: 42 }
        const one: TicketListRow = { ticketGroupHeader: 'Top 20', count: 1 }
        expect(
            JSON.stringify((wrapped[0].render!(undefined, many, 0, 1) as { children: JSX.Element }).children)
        ).toContain('42 tickets match current filters')
        expect(
            JSON.stringify((wrapped[0].render!(undefined, one, 0, 1) as { children: JSX.Element }).children)
        ).toContain('1 ticket matches current filters')
    })

    it('collapses the remaining cells of a header row', () => {
        expect(wrapped[1].render!(undefined, header, 0, 1)).toEqual({ props: { colSpan: 0 } })
        expect(wrapped[2].render!(undefined, header, 0, 1)).toEqual({ props: { colSpan: 0 } })
    })

    it('delegates ticket rows to the original renderers', () => {
        expect(wrapped[0].render!(undefined, free, 0, 1)).toBe('one:f')
        expect(wrapped[2].render!(undefined, free, 0, 1)).toBe('three:f')
    })

    it('preserves column props like width, title, and sorter', () => {
        expect(wrapped[0].width).toBe(80)
        expect(wrapped[1].sorter).toBe(true)
        expect(wrapped[2].title).toBe('Three')
    })
})
