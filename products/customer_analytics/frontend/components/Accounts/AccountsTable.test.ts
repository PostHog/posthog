import type {
    CustomPropertyDefinitionApi,
    CustomPropertySourceApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

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

const createCustomPropertySource = (): CustomPropertySourceApi => ({
    id: 'source-1',
    definition: 'custom-property-1',
    key_column: 'external_id',
    consecutive_failures: 0,
    last_synced_at: null,
    last_sync_error: null,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    sync_frequency_interval_seconds: null,
    next_sync_at: null,
    latest_run: null,
    external_data_source: null,
    table_name: null,
    saved_query_name: null,
})

const createCustomPropertyDefinition = (
    overrides: Partial<CustomPropertyDefinitionApi> = {}
): CustomPropertyDefinitionApi => ({
    id: 'custom-property-1',
    name: 'Health score',
    display_type: 'number',
    is_canonical: false,
    source: null,
    has_workflow_reference: false,
    created_at: '2026-01-01T00:00:00Z',
    created_by: null,
    updated_at: null,
    references: [],
    ...overrides,
})

describe('isCustomPropertyEditable', () => {
    it.each([
        ['manual', createCustomPropertyDefinition(), true],
        ['canonical', createCustomPropertyDefinition({ is_canonical: true }), false],
        ['data warehouse managed', createCustomPropertyDefinition({ source: createCustomPropertySource() }), false],
        ['workflow managed', createCustomPropertyDefinition({ has_workflow_reference: true }), true],
    ])('marks %s definitions editable unless PostHog or the warehouse manages their values', (_, value, expected) => {
        expect(isCustomPropertyEditable(value)).toBe(expected)
    })
})

describe('isCustomPropertyValueValid', () => {
    it.each([
        ['accepts HTTP URLs', 'http://example.com', true],
        ['accepts HTTPS URLs', 'https://example.com', true],
        ['rejects a URL without a scheme', 'example.com', false],
        ['rejects unsupported URL schemes', 'ftp://example.com', false],
    ])('%s', (_, value, expected) => {
        expect(isCustomPropertyValueValid(value, createCustomPropertyDefinition({ display_type: 'link' }))).toBe(
            expected
        )
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
