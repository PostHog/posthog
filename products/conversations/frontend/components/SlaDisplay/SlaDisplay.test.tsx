import { getSlaState } from './SlaDisplay'

describe('getSlaState', () => {
    beforeEach(() => {
        jest.useFakeTimers().setSystemTime(new Date('2026-08-11T12:00:00Z'))
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it.each([
        ['breached', '2026-08-11T11:59:00Z', 'breached'],
        ['at risk', '2026-08-11T12:30:00Z', 'at-risk'],
        ['on track', '2026-08-11T13:00:00Z', 'on-track'],
    ])('returns %s for an SLA due at %s', (_label, slaDueAt, expectedState) => {
        expect(getSlaState(slaDueAt)).toBe(expectedState)
    })
})
