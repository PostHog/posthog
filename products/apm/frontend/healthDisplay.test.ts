import type { HealthRowApi } from './generated/api.schemas'
import { formatApdex } from './healthDisplay'

describe('formatApdex', () => {
    it.each([
        ['a score', 0.6149, '0.61'],
        ['no score', null, '—'],
    ])('shows %s', (_, score, expected) => {
        expect(formatApdex(score)).toBe(expected)
    })

    it('shows a dash for a row cached before the score existed', () => {
        const cachedRow = { request_rate: 1, error_rate: 0, p95_ms: 10, span_count: 1, error_count: 0 } as HealthRowApi
        expect(formatApdex(cachedRow.apdex)).toBe('—')
    })
})
