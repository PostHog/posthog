import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { passkeySettingsLogic } from './passkeySettingsLogic'

export function PasskeyAddForm(): JSX.Element {
    const { registrationStep, error } = useValues(passkeySettingsLogic)
    const { beginRegistration, clearError } = useActions(passkeySettingsLogic)

    const [newPasskeyLabel, setNewPasskeyLabel] = useState('')

    const handleAddPasskey = (): void => {
        const label = newPasskeyLabel.trim() || 'My Passkey'
        beginRegistration(label)
        setNewPasskeyLabel('')
    }

    const isRegistering = registrationStep === 'registering' || registrationStep === 'verifying'

    return (
        <div className="space-y-4">
            {error && (
                <LemonBanner type="error" onClose={clearError}>
                    {error}
                </LemonBanner>
            )}

            {registrationStep === 'complete' && (
                <LemonBanner type="success">
                    <div className="flex items-center gap-2">
                        <IconCheckCircle className="text-success" />
                        Passkey added and verified successfully!
                    </div>
                </LemonBanner>
            )}

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

            {registrationStep === 'verifying' && (
                <LemonBanner type="info">
                    <div className="flex items-center gap-2">
                        <Spinner />
                        Please verify your passkey to complete registration...
                    </div>
                </LemonBanner>
            )}
        </div>
    )
}
