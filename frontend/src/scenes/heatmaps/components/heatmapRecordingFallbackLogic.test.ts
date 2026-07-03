import { buildRecordingsQueryForUrl } from './heatmapRecordingFallbackLogic'

describe('heatmapRecordingFallbackLogic', () => {
    it('searches recordings by pages actually visited during the session, not just session start', () => {
        const query = buildRecordingsQueryForUrl('https://example.com/pricing')
        expect(query.properties).toEqual([
            {
                type: 'recording',
                key: 'visited_page',
                operator: 'icontains',
                value: ['https://example.com/pricing'],
            },
        ])
        expect(query.order).toBe('start_time')
        expect(query.order_direction).toBe('DESC')
    })
})
