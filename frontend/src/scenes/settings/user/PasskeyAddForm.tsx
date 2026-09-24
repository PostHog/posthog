import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { type RegistrationStep, passkeySettingsLogic } from './passkeySettingsLogic'

// A passkey that awaits verification cannot sign the user in yet, and a second registration would
// replace it as the one the banner offers to verify. So hold the add controls until the user either
// verifies that passkey or dismisses the prompt.
function getAddDisabledReason(registrationStep: RegistrationStep): string | undefined {
    if (registrationStep === 'registering' || registrationStep === 'verifying') {
        return 'Registration in progress...'
    }
    if (registrationStep === 'awaiting_verification') {
        return 'Verify your new passkey first'
    }
    return undefined
}

function RegistrationBanners(): JSX.Element {
    const { registrationStep, pendingVerificationId, error } = useValues(passkeySettingsLogic)
    const { clearError, verifyPasskey, dismissVerificationPrompt } = useActions(passkeySettingsLogic)

    return (
        <>
            {error && (
                <LemonBanner type="error" onClose={clearError}>
                    {error}
                </LemonBanner>
            )}

            {registrationStep === 'complete' && <LemonBanner type="success">Passkey added and verified.</LemonBanner>}

            {registrationStep === 'awaiting_verification' && pendingVerificationId !== null && (
                <LemonBanner
                    type="info"
                    onClose={dismissVerificationPrompt}
                    action={{
                        children: 'Verify passkey',
                        onClick: () => verifyPasskey(pendingVerificationId),
                        'data-attr': 'verify-new-passkey',
                    }}
                >
                    Your passkey is saved. Verify it now to use it for sign-in.
                </LemonBanner>
            )}

            {registrationStep === 'verifying' && (
                <LemonBanner type="info" icon={<Spinner />}>
                    Waiting for your passkey...
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
    const addDisabledReason = getAddDisabledReason(registrationStep)

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
                    disabledReason={addDisabledReason}
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
    const addDisabledReason = getAddDisabledReason(registrationStep)

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
                        disabled={!!addDisabledReason}
                        onPressEnter={handleAddPasskey}
                        maxLength={200}
                    />
                </div>
                <LemonButton
                    type="primary"
                    onClick={handleAddPasskey}
                    loading={isRegistering}
                    disabledReason={addDisabledReason}
                >
                    {registrationStep === 'verifying' ? 'Verifying...' : 'Add passkey'}
                </LemonButton>
            </div>
        </div>
    )
}
