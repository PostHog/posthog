import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { passkeySettingsLogic } from './passkeySettingsLogic'

function RegistrationBanners(): JSX.Element | null {
    const { registrationStep, error } = useValues(passkeySettingsLogic)
    const { clearError } = useActions(passkeySettingsLogic)

    if (!error && registrationStep !== 'complete' && registrationStep !== 'verifying') {
        return null
    }

    return (
        <>
            {error && (
                <LemonBanner type="error" onClose={clearError}>
                    {error}
                </LemonBanner>
            )}

            {registrationStep === 'complete' && (
                <LemonBanner type="success">Passkey added and verified successfully!</LemonBanner>
            )}

            {registrationStep === 'verifying' && (
                <LemonBanner type="info" icon={<Spinner />}>
                    Please verify your passkey to complete registration...
                </LemonBanner>
            )}
        </>
    )
}

export function PasskeyAddFormEmpty(): JSX.Element {
    const { registrationStep } = useValues(passkeySettingsLogic)
    const { beginRegistration } = useActions(passkeySettingsLogic)

    const handleAddPasskey = (): void => {
        beginRegistration('My Passkey')
    }

    const isRegistering = registrationStep === 'registering' || registrationStep === 'verifying'

    return (
        <div className="flex flex-col items-start space-y-4">
            <div className="w-full">
                <RegistrationBanners />
            </div>

            <div>
                <p className="text-muted mb-4 max-w-lg">
                    Passkeys provide a faster, more seamless sign-in experience. Use your device's biometric
                    authentication or a security key to sign in without passwords.
                </p>
                <LemonButton
                    type="primary"
                    onClick={handleAddPasskey}
                    loading={isRegistering}
                    disabledReason={isRegistering ? 'Registration in progress...' : undefined}
                >
                    {registrationStep === 'verifying' ? 'Verifying...' : 'Add passkey'}
                </LemonButton>
            </div>
        </div>
    )
}

export function PasskeyAddForm(): JSX.Element {
    const { registrationStep } = useValues(passkeySettingsLogic)
    const { beginRegistration } = useActions(passkeySettingsLogic)

    const [newPasskeyLabel, setNewPasskeyLabel] = useState('')

    const handleAddPasskey = (): void => {
        const label = newPasskeyLabel.trim() || 'My Passkey'
        beginRegistration(label)
        setNewPasskeyLabel('')
    }

    const isRegistering = registrationStep === 'registering' || registrationStep === 'verifying'

    return (
        <div className="space-y-4">
            <RegistrationBanners />

            <div className="flex gap-2 items-end">
                <div className="flex-1">
                    <label className="font-medium text-sm mb-1 block">Add a new passkey</label>
                    <LemonInput
                        placeholder="Passkey name (optional)"
                        value={newPasskeyLabel}
                        onChange={setNewPasskeyLabel}
                        disabled={isRegistering}
                        onPressEnter={handleAddPasskey}
                        maxLength={200}
                    />
                </div>
                <LemonButton
                    type="primary"
                    onClick={handleAddPasskey}
                    loading={isRegistering}
                    disabledReason={isRegistering ? 'Registration in progress...' : undefined}
                >
                    {registrationStep === 'verifying' ? 'Verifying...' : 'Add passkey'}
                </LemonButton>
            </div>
        </div>
    )
}
