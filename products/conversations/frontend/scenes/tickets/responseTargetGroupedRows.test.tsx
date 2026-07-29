import { LemonTableColumns } from '@posthog/lemon-ui'

import { Ticket } from '../../types'
import {
    buildResponseTargetGroupedRows,
    isResponseTargetHeaderRow,
    TicketListRow,
    withResponseTargetHeaderRows,
} from './responseTargetGroupedRows'

const ticket = (id: string, tags: string[]): Ticket => ({ id, tags }) as unknown as Ticket

const triage = ticket('t', [])
const churn = ticket('ch', ['churn_risk'])
const top20 = ticket('t20', ['top_20'])
const enterprise = ticket('e', ['plan_enterprise'])
const free = ticket('f', ['plan_free'])
const community = ticket('co', ['community'])

// A six-tier fixture ladder — enough groups to exercise leading/inner/trailing
// gaps, independent of the example default ladder.
const GROUPS = [
    { label: 'Triage', tags: ['needs_triage'] },
    { label: 'Churn risk', tags: ['churn_risk'] },
    { label: 'Top 20', tags: ['top_20'] },
    { label: 'Enterprise', tags: ['plan_enterprise'] },
    { label: 'Free plan', tags: ['plan_free'] },
    { label: 'Community', tags: ['community'] },
]

const SINGLE_PAGE = {
    groups: GROUPS,
    desc: false,
    isFirstPage: true,
    isLastPage: true,
}

describe('buildResponseTargetGroupedRows', () => {
    it('returns an empty list unchanged (empty state, no headers)', () => {
        expect(buildResponseTargetGroupedRows([], SINGLE_PAGE)).toEqual([])
    })

    it('groups tickets under headers and marks provably-empty groups between them', () => {
        const rows = buildResponseTargetGroupedRows([churn, enterprise], SINGLE_PAGE)
        expect(rows).toEqual([
            { responseTargetHeader: 'Triage', empty: true },
            { responseTargetHeader: 'Churn risk' },
            churn,
            { responseTargetHeader: 'Top 20', empty: true },
            { responseTargetHeader: 'Enterprise' },
            enterprise,
            { responseTargetHeader: 'Free plan', empty: true },
            { responseTargetHeader: 'Community', empty: true },
        ])
    })

    it('emits one header for a run of same-group tickets', () => {
        const rows = buildResponseTargetGroupedRows(
            [ticket('a', ['plan_free']), ticket('b', ['plan_free'])],
            SINGLE_PAGE
        )
        expect(rows.filter((r) => isResponseTargetHeaderRow(r) && !r.empty)).toHaveLength(1)
    })

    it('omits leading empties when not the first page, trailing when not the last', () => {
        const middlePage = buildResponseTargetGroupedRows([enterprise], {
            ...SINGLE_PAGE,
            isFirstPage: false,
            isLastPage: false,
        })
        expect(middlePage).toEqual([{ responseTargetHeader: 'Enterprise' }, enterprise])
    })

    it('reverses the ladder when sorted descending', () => {
        const rows = buildResponseTargetGroupedRows([community, free], {
            ...SINGLE_PAGE,
            desc: true,
            isLastPage: false,
        })
        expect(rows[0]).toEqual({ responseTargetHeader: 'Community' })
        expect(rows[1]).toEqual(community)
        expect(rows[2]).toEqual({ responseTargetHeader: 'Free plan' })
        expect(rows[3]).toEqual(free)
        // not the last page → no trailing empties beyond Free plan
        expect(rows).toHaveLength(4)
    })

    it('marks inner gaps as empty on any page (adjacency proves emptiness)', () => {
        const rows = buildResponseTargetGroupedRows([triage, top20], {
            ...SINGLE_PAGE,
            isFirstPage: false,
            isLastPage: false,
        })
        expect(rows).toEqual([
            { responseTargetHeader: 'Triage' },
            triage,
            { responseTargetHeader: 'Churn risk', empty: true },
            { responseTargetHeader: 'Top 20' },
            top20,
        ])
    })

    it('stamps headers with server counts by group rank when provided', () => {
        const rows = buildResponseTargetGroupedRows([churn, enterprise], {
            ...SINGLE_PAGE,
            counts: { '1': 12, '3': 4 },
        })
        expect(rows).toContainEqual({ responseTargetHeader: 'Churn risk', count: 12 })
        expect(rows).toContainEqual({ responseTargetHeader: 'Enterprise', count: 4 })
        // groups absent from the counts map are zero-matching
        expect(rows).toContainEqual({ responseTargetHeader: 'Top 20', empty: true, count: 0 })
    })

    it('keeps counts keyed by original ladder rank when descending reverses the walk', () => {
        const rows = buildResponseTargetGroupedRows([enterprise, churn], {
            ...SINGLE_PAGE,
            desc: true,
            counts: { '1': 12, '3': 4 },
        })
        // ranks are ladder positions (Churn risk = 1, Enterprise = 3) regardless of display order
        expect(rows).toContainEqual({ responseTargetHeader: 'Enterprise', count: 4 })
        expect(rows).toContainEqual({ responseTargetHeader: 'Churn risk', count: 12 })
        expect(rows).toContainEqual({ responseTargetHeader: 'Community', empty: true, count: 0 })
        // descending: Enterprise renders before Churn risk
        const labels = rows.filter(isResponseTargetHeaderRow).map((r) => r.responseTargetHeader)
        expect(labels.indexOf('Enterprise')).toBeLessThan(labels.indexOf('Churn risk'))
    })

    it('groups against a custom ladder', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        const vip = ticket('v', ['vip'])
        const rows = buildResponseTargetGroupedRows([vip, free], { ...SINGLE_PAGE, groups })
        expect(rows).toEqual([{ responseTargetHeader: 'VIPs' }, vip, { responseTargetHeader: 'Everyone else' }, free])
    })

    it('does not mutate the caller-owned groups array when descending', () => {
        const groups = [
            { label: 'VIPs', tags: ['vip'] },
            { label: 'Everyone else', tags: ['plan_free'] },
        ]
        buildResponseTargetGroupedRows([free], { ...SINGLE_PAGE, groups, desc: true })
        expect(groups.map((g) => g.label)).toEqual(['VIPs', 'Everyone else'])
    })
})

describe('withResponseTargetHeaderRows', () => {
    const columns: LemonTableColumns<Ticket> = [
        { key: 'one', title: 'One', width: 80, render: (_, t) => `one:${t.id}` },
        { key: 'two', title: 'Two', sorter: true, render: (_, t) => `two:${t.id}` },
        { key: 'three', title: 'Three', render: (_, t) => `three:${t.id}` },
    ]
    const wrapped = withResponseTargetHeaderRows(columns)
    const header: TicketListRow = { responseTargetHeader: 'Enterprise' }

    it('renders the header label spanning every column in the first cell', () => {
        const cell = wrapped[0].render!(undefined, header, 0, 1) as { children: JSX.Element; props: object }
        expect(cell.props).toEqual({ colSpan: 3 })
        expect(JSON.stringify(cell.children)).toContain('Enterprise')
    })

    it('renders the zero-match note on empty group headers', () => {
        const emptyHeader: TicketListRow = { responseTargetHeader: 'Top 20', empty: true }
        const cell = wrapped[0].render!(undefined, emptyHeader, 0, 1) as { children: JSX.Element }
        expect(JSON.stringify(cell.children)).toContain('zero tickets match current filters')
    })

    it('renders match counts on populated headers, with singular grammar for one', () => {
        const many: TicketListRow = { responseTargetHeader: 'Enterprise', count: 42 }
        const one: TicketListRow = { responseTargetHeader: 'Top 20', count: 1 }
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
