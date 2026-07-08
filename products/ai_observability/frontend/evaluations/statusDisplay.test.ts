import { statusReasonLabel, statusReasonRecoveryLabel } from './statusDisplay'

describe('statusDisplay', () => {
    describe('statusReasonLabel', () => {
        it.each([
            ['provider_key_required' as const, 'No provider API key configured'],
            ['trial_limit_reached' as const, 'Trial evaluation limit reached'],
            ['model_not_allowed' as const, 'Model not available on the trial plan'],
            ['provider_key_deleted' as const, 'Provider API key was deleted'],
            ['no_default_model' as const, 'No default model available for the selected provider'],
            ['provider_key_invalid' as const, 'Provider API key is invalid'],
            ['provider_key_permission_denied' as const, 'Provider API key lacks model access'],
            ['provider_key_quota_exceeded' as const, 'Provider API key quota exceeded'],
            ['provider_key_rate_limited' as const, 'Provider API key is rate limited'],
            ['model_not_found' as const, 'Model not found'],
            ['hog_error' as const, 'Hog evaluation code failed'],
        ])('maps %s to user-facing copy', (reason, expected) => {
            expect(statusReasonLabel(reason)).toBe(expected)
        })

        it('returns a generic fallback when reason is null or undefined', () => {
            expect(statusReasonLabel(null)).toBe('Disabled by the system')
            expect(statusReasonLabel(undefined)).toBe('Disabled by the system')
        })
    })

    describe('statusReasonRecoveryLabel', () => {
        it.each([
            [
                'provider_key_required' as const,
                'Add a provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'trial_limit_reached' as const,
                'Add a provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'model_not_allowed' as const,
                'Choose a supported model or add a provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'provider_key_deleted' as const,
                'Fix or replace the provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'provider_key_invalid' as const,
                'Fix or replace the provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'provider_key_permission_denied' as const,
                'Fix or replace the provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'provider_key_quota_exceeded' as const,
                'Fix or replace the provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'provider_key_rate_limited' as const,
                'Fix or replace the provider API key in settings, then re-enable the evaluation to resume running.',
            ],
            [
                'no_default_model' as const,
                'Choose an available model, then re-enable the evaluation to resume running.',
            ],
            ['model_not_found' as const, 'Choose an available model, then re-enable the evaluation to resume running.'],
            ['hog_error' as const, 'Fix the Hog code, then re-enable the evaluation to resume running.'],
        ])('maps %s to recovery copy', (reason, expected) => {
            expect(statusReasonRecoveryLabel(reason)).toBe(expected)
        })

        it('returns a generic fallback when reason is null or undefined', () => {
            expect(statusReasonRecoveryLabel(null)).toBe(
                'Fix the configuration, then re-enable the evaluation to resume running.'
            )
            expect(statusReasonRecoveryLabel(undefined)).toBe(
                'Fix the configuration, then re-enable the evaluation to resume running.'
            )
        })
    })
})
