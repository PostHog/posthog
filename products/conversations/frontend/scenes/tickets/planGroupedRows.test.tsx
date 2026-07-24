import { LemonTableColumns } from '@posthog/lemon-ui'

import { Ticket } from '../../types'
import {
    buildPlanGroupedRows,
    isPlanHeaderRow,
    isPlanOrdered,
    TicketListRow,
    withPlanHeaderRows,
} from './planGroupedRows'

const ticket = (id: string, tags: string[]): Ticket => ({ id, tags }) as unknown as Ticket

const triage = ticket('t', [])
const churn = ticket('ch', ['churn_risk'])
const top20 = ticket('t20', ['top_20'])
const enterprise = ticket('e', ['plan_enterprise'])
const free = ticket('f', ['plan_free'])
const community = ticket('co', ['community'])

const SINGLE_PAGE = { desc: false, isFirstPage: true, isLastPage: true }

describe('isPlanOrdered', () => {
    it('accepts ascending plan-rank order (and desc rejects it)', () => {
        expect(isPlanOrdered([triage, churn, enterprise, free], false)).toBe(true)
        expect(isPlanOrdered([triage, churn, enterprise, free], true)).toBe(false)
    })

    it('accepts descending order when desc', () => {
        expect(isPlanOrdered([free, enterprise, churn], true)).toBe(true)
    })

    it('rejects interleaved (stale, non-plan-sorted) data', () => {
        expect(isPlanOrdered([churn, free, churn], false)).toBe(false)
        expect(isPlanOrdered([churn, free, churn], true)).toBe(false)
    })

    it('accepts empty and single-ticket lists', () => {
        expect(isPlanOrdered([], false)).toBe(true)
        expect(isPlanOrdered([free], true)).toBe(true)
    })
})

describe('buildPlanGroupedRows', () => {
    it('returns an empty list unchanged (empty state, no headers)', () => {
        expect(buildPlanGroupedRows([], SINGLE_PAGE)).toEqual([])
    })

    it('groups tickets under headers and marks provably-empty groups between them', () => {
        const rows = buildPlanGroupedRows([churn, enterprise], SINGLE_PAGE)
        expect(rows).toEqual([
            { planHeader: 'Triage', empty: true },
            { planHeader: 'Churn risk' },
            churn,
            { planHeader: 'Top 20', empty: true },
            { planHeader: 'Enterprise' },
            enterprise,
            { planHeader: 'Onboarding', empty: true },
            { planHeader: 'Scale & Teams & YC', empty: true },
            { planHeader: 'Boost & Startup & Pay-as-you-go paying', empty: true },
            { planHeader: 'Pay-as-you-go free', empty: true },
            { planHeader: 'Free plan', empty: true },
            { planHeader: 'Community', empty: true },
        ])
    })

    it('emits one header for a run of same-group tickets', () => {
        const rows = buildPlanGroupedRows([ticket('a', ['plan_free']), ticket('b', ['plan_free'])], SINGLE_PAGE)
        expect(rows.filter((r) => isPlanHeaderRow(r) && !r.empty)).toHaveLength(1)
    })

    it('omits leading empties when not the first page, trailing when not the last', () => {
        const middlePage = buildPlanGroupedRows([enterprise], { desc: false, isFirstPage: false, isLastPage: false })
        expect(middlePage).toEqual([{ planHeader: 'Enterprise' }, enterprise])
    })

    it('reverses the ladder when sorted descending', () => {
        const rows = buildPlanGroupedRows([community, free], {
            desc: true,
            isFirstPage: true,
            isLastPage: false,
        })
        expect(rows[0]).toEqual({ planHeader: 'Community' })
        expect(rows[1]).toEqual(community)
        expect(rows[2]).toEqual({ planHeader: 'Free plan' })
        expect(rows[3]).toEqual(free)
        // not the last page → no trailing empties beyond Free plan
        expect(rows).toHaveLength(4)
    })

    it('marks inner gaps as empty on any page (adjacency proves emptiness)', () => {
        const rows = buildPlanGroupedRows([triage, top20], { desc: false, isFirstPage: false, isLastPage: false })
        expect(rows).toEqual([
            { planHeader: 'Triage' },
            triage,
            { planHeader: 'Churn risk', empty: true },
            { planHeader: 'Top 20' },
            top20,
        ])
    })

    it('stamps headers with server counts by plan rank when provided', () => {
        const rows = buildPlanGroupedRows([churn, enterprise], {
            ...SINGLE_PAGE,
            counts: { '1': 12, '3': 4 },
        })
        expect(rows).toContainEqual({ planHeader: 'Churn risk', count: 12 })
        expect(rows).toContainEqual({ planHeader: 'Enterprise', count: 4 })
        // groups absent from the counts map are zero-matching
        expect(rows).toContainEqual({ planHeader: 'Top 20', empty: true, count: 0 })
    })

    it('keeps counts keyed by original ladder rank when descending reverses the walk', () => {
        const rows = buildPlanGroupedRows([enterprise, churn], {
            desc: true,
            isFirstPage: true,
            isLastPage: true,
            counts: { '1': 12, '3': 4 },
        })
        // ranks are ladder positions (Churn risk = 1, Enterprise = 3) regardless of display order
        expect(rows).toContainEqual({ planHeader: 'Enterprise', count: 4 })
        expect(rows).toContainEqual({ planHeader: 'Churn risk', count: 12 })
        expect(rows).toContainEqual({ planHeader: 'Community', empty: true, count: 0 })
        // descending: Enterprise renders before Churn risk
        const labels = rows.filter(isPlanHeaderRow).map((r) => r.planHeader)
        expect(labels.indexOf('Enterprise')).toBeLessThan(labels.indexOf('Churn risk'))
    })
})

describe('withPlanHeaderRows', () => {
    const columns: LemonTableColumns<Ticket> = [
        { key: 'one', title: 'One', width: 80, render: (_, t) => `one:${t.id}` },
        { key: 'two', title: 'Two', sorter: true, render: (_, t) => `two:${t.id}` },
        { key: 'three', title: 'Three', render: (_, t) => `three:${t.id}` },
    ]
    const wrapped = withPlanHeaderRows(columns)
    const header: TicketListRow = { planHeader: 'Enterprise' }

    it('renders the header label spanning every column in the first cell', () => {
        const cell = wrapped[0].render!(undefined, header, 0, 1) as { children: JSX.Element; props: object }
        expect(cell.props).toEqual({ colSpan: 3 })
        expect(JSON.stringify(cell.children)).toContain('Enterprise')
    })

    it('renders the zero-match note on empty group headers', () => {
        const emptyHeader: TicketListRow = { planHeader: 'Top 20', empty: true }
        const cell = wrapped[0].render!(undefined, emptyHeader, 0, 1) as { children: JSX.Element }
        expect(JSON.stringify(cell.children)).toContain('zero tickets match current filters')
    })

    it('renders match counts on populated headers, with singular grammar for one', () => {
        const many: TicketListRow = { planHeader: 'Enterprise', count: 42 }
        const one: TicketListRow = { planHeader: 'Top 20', count: 1 }
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
