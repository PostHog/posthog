import { isTwoFactorGateDetail } from './twoFactorGate'

describe('isTwoFactorGateDetail', () => {
    it.each([
        ['exact setup detail', '2FA setup required', true],
        ['exact verification detail', '2FA verification required', true],
        ['detail wrapped by a call site', 'Failed to update organization: 2FA setup required', true],
        ['unrelated error', 'Failed to update organization: Unknown error', false],
        ['unrelated 2FA copy', 'Failed to update passkey 2FA setting', false],
        ['non-string message', undefined, false],
    ])('%s', (_name, message, expected) => {
        expect(isTwoFactorGateDetail(message)).toBe(expected)
    })
})
