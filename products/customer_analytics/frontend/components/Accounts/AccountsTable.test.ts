import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import {
    buildHistoryDisplay,
    getCanonicalPropertyTab,
    isCustomPropertyEditable,
    isCustomPropertyValueValid,
} from './AccountsTable'

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

describe('isCustomPropertyEditable', () => {
    const definition = (overrides: Partial<CustomPropertyDefinitionApi> = {}): CustomPropertyDefinitionApi =>
        ({ is_canonical: false, source: null, references: [], ...overrides }) as CustomPropertyDefinitionApi

    it.each([
        ['manual', definition(), true],
        ['canonical', definition({ is_canonical: true }), false],
        ['data warehouse managed', definition({ source: {} as CustomPropertyDefinitionApi['source'] }), false],
        [
            'workflow managed',
            definition({
                references: [{ id: 'workflow-1', name: 'Update value', status: 'active', type: 'workflow' }],
            }),
            false,
        ],
    ])('marks %s definitions editable only when users can safely set their value', (_, value, expected) => {
        expect(isCustomPropertyEditable(value)).toBe(expected)
    })
})

describe('isCustomPropertyValueValid', () => {
    const definition = (displayType: CustomPropertyDefinitionApi['display_type']): CustomPropertyDefinitionApi =>
        ({ display_type: displayType }) as CustomPropertyDefinitionApi

    it.each([
        ['accepts HTTP URLs', 'http://example.com', true],
        ['accepts HTTPS URLs', 'https://example.com', true],
        ['rejects a URL without a scheme', 'example.com', false],
        ['rejects unsupported URL schemes', 'ftp://example.com', false],
    ])('%s', (_, value, expected) => {
        expect(isCustomPropertyValueValid(value, definition('link'))).toBe(expected)
    })
})

describe('getCanonicalPropertyTab', () => {
    const definition = (name: string, isCanonical: boolean): CustomPropertyDefinitionApi =>
        ({ name, is_canonical: isCanonical }) as CustomPropertyDefinitionApi

    it('routes the last Slack message to the channel summaries', () => {
        expect(getCanonicalPropertyTab(definition('Last Slack message at', true))).toBe('conversations')
    })

    it('does not link an ordinary property a user happened to name the same', () => {
        expect(getCanonicalPropertyTab(definition('Last Slack message at', false))).toBeUndefined()
    })

    it('does not link a canonical property with no tab of its own', () => {
        expect(getCanonicalPropertyTab(definition('Some future canonical property', true))).toBeUndefined()
    })
})
