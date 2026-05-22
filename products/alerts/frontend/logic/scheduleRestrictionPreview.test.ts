import { estimateCheckSlotsNext24h } from './scheduleRestrictionPreview'

describe('scheduleRestrictionPreview', () => {
    const overnight = [{ start: '22:00', end: '07:00' }]

    it('returns full slot count when no quiet hours are configured', () => {
        expect(estimateCheckSlotsNext24h(null, 'UTC', 60)).toBe(24)
        expect(estimateCheckSlotsNext24h(undefined, 'UTC', 15)).toBe(96)
    })

    it('counts fewer hourly slots when overnight quiet hours block most of the day', () => {
        const count = estimateCheckSlotsNext24h(overnight, 'UTC', 60)
        expect(count).toBeGreaterThan(0)
        expect(count).toBeLessThan(24)
    })

    it('counts fewer 15-minute slots than 96 when quiet hours apply', () => {
        const count = estimateCheckSlotsNext24h(overnight, 'UTC', 15)
        expect(count).toBeGreaterThan(0)
        expect(count).toBeLessThan(96)
    })
})
