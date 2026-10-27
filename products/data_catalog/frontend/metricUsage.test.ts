import { dayjs } from 'lib/dayjs'

import type { DataCatalogMetricApi } from './generated/api.schemas'
import { isCleanupCandidate } from './metricUsage'

const NOW = dayjs('2026-10-27T12:00:00Z')

function daysAgo(days: number): string {
    return NOW.subtract(days, 'day').toISOString()
}

describe('isCleanupCandidate', () => {
    it.each([
        ['an approved metric last run 100 days ago', { last_run_at: daysAgo(100) }, true],
        ['an approved metric never run', { last_run_at: null }, true],
        ['an approved metric created 30 days ago and never run', { created_at: daysAgo(30), last_run_at: null }, false],
        ['an approved metric run 10 days ago', { last_run_at: daysAgo(10) }, false],
        ['a proposed metric never run', { status: 'proposed', last_run_at: null }, false],
        ['a drifted approved metric never run', { is_drifted: true, last_run_at: null }, false],
    ])('%s is a cleanup candidate: %s', (_label, overrides, expected) => {
        const metric = {
            name: 'weekly_active_users',
            status: 'approved',
            is_drifted: false,
            created_at: daysAgo(200),
            ...overrides,
        } as DataCatalogMetricApi
        expect(isCleanupCandidate(metric, NOW)).toBe(expected)
    })
})
