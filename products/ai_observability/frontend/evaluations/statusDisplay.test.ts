import { statusReasonLabel } from './statusDisplay'

describe('statusReasonLabel', () => {
    it.each([
        ['trial_limit_reached' as const, 'Trial evaluation limit reached'],
        ['model_not_allowed' as const, 'Model not available on the trial plan'],
        ['provider_key_deleted' as const, 'Provider API key was deleted'],
    ])('maps %s to user-facing copy', (reason, expected) => {
        expect(statusReasonLabel(reason)).toBe(expected)
    })

    it('returns a generic fallback when reason is null or undefined', () => {
        expect(statusReasonLabel(null)).toBe('Disabled by the system')
        expect(statusReasonLabel(undefined)).toBe('Disabled by the system')
    })
})
