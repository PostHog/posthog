import { dropHandledAuthGateExceptions } from './loadPostHogJS'

describe('dropHandledAuthGateExceptions', () => {
    it('passes non-exception events through unchanged', () => {
        const event = { event: '$pageview', properties: { $current_url: '/foo' } }
        expect(dropHandledAuthGateExceptions(event)).toBe(event)
    })

    it('passes $exception events that are real crashes through', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
        }
        expect(dropHandledAuthGateExceptions(event)).toBe(event)
    })

    // Each of these is the message `ApiError` sets from the backend `detail` for a handled auth
    // gate, so a rejected request is expected control flow rather than a bug to report.
    it.each([
        ['2FA setup required', 'two_factor_setup_required'],
        ['2FA verification required', 'two_factor_verification_required'],
        ['This action requires you to be recently authenticated.', 'sensitive_action_required_reauth'],
    ])('drops the handled auth-gate exception with message "%s"', (value) => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'Error', value }] },
        }
        expect(dropHandledAuthGateExceptions(event)).toBeNull()
    })

    it('drops the gate even when it sits deeper in the exception list', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'reverseProxyCheckerLogic: query failed' },
                    { type: 'Error', value: '2FA setup required' },
                ],
            },
        }
        expect(dropHandledAuthGateExceptions(event)).toBeNull()
    })

    it('tolerates missing properties and a missing exception list', () => {
        expect(dropHandledAuthGateExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropHandledAuthGateExceptions({ event: '$exception', properties: {} })).toEqual({
            event: '$exception',
            properties: {},
        })
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropHandledAuthGateExceptions(null)).toBeNull()
    })
})
