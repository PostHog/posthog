import { formatChange } from './deploymentsDisplay'
import type { DeploymentVersionApi } from './generated/api.schemas'

const row = (overrides: Partial<DeploymentVersionApi>): DeploymentVersionApi => ({
    version: '1.1.0',
    first_seen: '2026-06-02T08:10:00Z',
    last_seen: '2026-06-02T08:50:00Z',
    requests: 100,
    error_count: 0,
    error_rate: 0,
    p95_ms: 10,
    previous_version: '1.0.0',
    error_rate_change: null,
    p95_change_pct: null,
    active: true,
    ...overrides,
})

describe('formatChange', () => {
    it.each([
        ['error', { error_rate_change: 0.3 }, '+30.0 pts'],
        ['error', { error_rate_change: -0.012 }, '−1.2 pts'],
        ['error', { error_rate_change: 0.0001 }, null],
        ['p95', { p95_change_pct: 200 }, '+200%'],
        ['p95', { p95_change_pct: -35.4 }, '−35%'],
        ['p95', { p95_change_pct: null }, null],
    ] as const)('%s %j -> %s', (metric, overrides, expected) => {
        expect(formatChange(metric, row(overrides))).toBe(expected)
    })
})
