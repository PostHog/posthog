import { useActions } from 'kea'
import { useEffect } from 'react'

import { PasskeyAddForm } from './PasskeyAddForm'
import { PasskeyList } from './PasskeyList'
import { PasskeyModals } from './PasskeyModals'
import { passkeySettingsLogic } from './passkeySettingsLogic'

export function PasskeySettings(): JSX.Element {
    const { loadPasskeys } = useActions(passkeySettingsLogic)

    useEffect(() => {
        loadPasskeys()
    }, [loadPasskeys])

    return (
        <div className="space-y-4">
            <div>
                <p className="text-muted mb-4">
                    Passkeys provide a secure way to sign in and can be used for both login and two-factor
                    authentication (2FA). Add a passkey to enable passwordless authentication.
                </p>
            </div>
            <PasskeyAddForm />
            <PasskeyList />
            <PasskeyModals />
        </div>
    )
}
