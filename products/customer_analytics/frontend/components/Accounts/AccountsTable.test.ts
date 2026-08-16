import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { buildHistoryDisplay, getCanonicalPropertyTab, isRowExpansionClick } from './AccountsTable'

const DAY = 24 * 60 * 60
const NOW_MS = 1_800_000_000_000
const NOW_S = NOW_MS / 1000

const daysAgo = (days: number): number => Math.floor(NOW_S - days * DAY)

describe('buildHistoryDisplay', () => {
    it('carries the last pre-window write forward so sparse histories still chart', () => {
        const points: [number, number][] = [
            [daysAgo(45), 100],
            [daysAgo(3), 120],
        ]
        const { latest, baseline, chartPoints } = buildHistoryDisplay(points, 7, NOW_MS)
        expect(latest).toEqual([daysAgo(3), 120])
        expect(baseline).toEqual([daysAgo(7), 100])
        expect(chartPoints).toEqual([
            [daysAgo(7), 100],
            [daysAgo(3), 120],
        ])
    })

    it('uses only in-window points when nothing precedes the window', () => {
        const points: [number, number][] = [
            [daysAgo(5), 10],
            [daysAgo(1), 30],
        ]
        const { baseline, chartPoints } = buildHistoryDisplay(points, 7, NOW_MS)
        expect(baseline).toEqual([daysAgo(5), 10])
        expect(chartPoints).toHaveLength(2)
    })

    it('falls back to a single carried point for a property with one write ever', () => {
        const points: [number, number][] = [[daysAgo(60), 500]]
        const { latest, chartPoints } = buildHistoryDisplay(points, 7, NOW_MS)
        expect(latest).toEqual([daysAgo(60), 500])
        expect(chartPoints).toHaveLength(1)
    })

    it('returns empty state for no history', () => {
        expect(buildHistoryDisplay([], 7, NOW_MS)).toEqual({ latest: null, baseline: null, chartPoints: [] })
    })
})

describe('getCanonicalPropertyTab', () => {
    const definition = (name: string, isCanonical: boolean): CustomPropertyDefinitionApi =>
        ({ name, is_canonical: isCanonical }) as CustomPropertyDefinitionApi

    it('routes the last Slack message to the channel summaries', () => {
        expect(getCanonicalPropertyTab(definition('Last Slack message at', true))).toBe('summaries')
    })

    it('does not link an ordinary property a user happened to name the same', () => {
        expect(getCanonicalPropertyTab(definition('Last Slack message at', false))).toBeUndefined()
    })

    it('does not link a canonical property with no tab of its own', () => {
        expect(getCanonicalPropertyTab(definition('Some future canonical property', true))).toBeUndefined()
    })
})

describe('isRowExpansionClick', () => {
    // The row handler sees clicks bubbled from anything inside it, and LemonButton doesn't stop them.
    const target = (html: string, selector: string): Element => {
        const host = document.createElement('tr')
        host.innerHTML = html
        return host.querySelector(selector)!
    }

    it('toggles for ordinary row content', () => {
        expect(isRowExpansionClick(target('<td><span class="cell">Acme</span></td>', '.cell'))).toBe(true)
    })

    it('leaves the expansion chevron to the expandable config, so it toggles once', () => {
        // TableRow already toggles from onRowExpand/onRowCollapse; toggling here too would expand
        // and immediately collapse the row.
        expect(
            isRowExpansionClick(target('<td class="LemonTable__toggle"><button class="chevron"/></td>', '.chevron'))
        ).toBe(false)
    })

    it.each([
        ['the account name link', '<td><a class="t" href="/x">Acme</a></td>'],
        ['a tag chip', '<td><div class="t" role="button">enterprise</div></td>'],
        ['the MemberSelect trigger', '<td><button class="t">Unassigned</button></td>'],
        ['an inline input', '<td><input class="t"/></td>'],
    ])('leaves %s to its own handler', (_label, html) => {
        expect(isRowExpansionClick(target(html, '.t'))).toBe(false)
    })

    it('ignores a click on a descendant of a control rather than the control itself', () => {
        expect(isRowExpansionClick(target('<td><button><span class="t">Unassigned</span></button></td>', '.t'))).toBe(
            false
        )
    })

    it('does not toggle for a non-element target', () => {
        expect(isRowExpansionClick(null)).toBe(false)
    })
})
