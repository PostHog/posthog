import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { PasskeyAddForm, PasskeyAddFormEmpty } from './PasskeyAddForm'
import { PasskeyList } from './PasskeyList'
import { PasskeyModals } from './PasskeyModals'
import { passkeySettingsLogic } from './passkeySettingsLogic'

export function PasskeySettings(): JSX.Element {
    const { passkeys } = useValues(passkeySettingsLogic)
    const { loadPasskeys } = useActions(passkeySettingsLogic)

    useEffect(() => {
        loadPasskeys()
    }, [loadPasskeys])

    const hasExistingPasskeys = passkeys.length > 0

    return (
        <div className="space-y-4">
            {hasExistingPasskeys ? <PasskeyAddForm /> : <PasskeyAddFormEmpty />}
            {hasExistingPasskeys && <PasskeyList />}
            <PasskeyModals />
        </div>
    )
}
