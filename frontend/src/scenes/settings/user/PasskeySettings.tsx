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
            <PasskeyAddForm />
            <PasskeyList />
            <PasskeyModals />
        </div>
    )
}
