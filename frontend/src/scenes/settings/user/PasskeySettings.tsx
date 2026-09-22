import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { PasskeyAddForm, PasskeyAddFormEmpty } from './PasskeyAddForm'
import { PasskeyList } from './PasskeyList'
import { PasskeyModals } from './PasskeyModals'
import { passkeySettingsLogic } from './passkeySettingsLogic'

export function PasskeySettings(): JSX.Element {
    const { passkeys, passkeysLoading } = useValues(passkeySettingsLogic)
    const { user } = useValues(userLogic)
    const { loadPasskeys, prepareRegistration } = useActions(passkeySettingsLogic)
    const hasSSOEnforcement = !!user?.has_sso_enforcement

    useEffect(() => {
        loadPasskeys()
    }, [loadPasskeys])

    useEffect(() => {
        // Fetch the registration options before the user clicks, so the browser prompt opens
        // inside the click's user activation instead of after a request has spent it.
        if (!hasSSOEnforcement) {
            prepareRegistration()
        }
    }, [hasSSOEnforcement, prepareRegistration])

    if (passkeysLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="h-32" />
                <LemonSkeleton className="h-24" />
            </div>
        )
    }

    const hasExistingPasskeys = passkeys.length > 0

    return (
        <div className="space-y-4">
            {hasSSOEnforcement && (
                <LemonBanner type="warning">
                    Passkeys can't be added because your organization requires SSO.
                </LemonBanner>
            )}
            {!hasSSOEnforcement && (hasExistingPasskeys ? <PasskeyAddForm /> : <PasskeyAddFormEmpty />)}
            {hasExistingPasskeys && <PasskeyList />}
            <PasskeyModals />
        </div>
    )
}
