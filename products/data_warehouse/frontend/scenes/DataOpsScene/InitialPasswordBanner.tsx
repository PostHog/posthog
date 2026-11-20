import { useActions, useValues } from 'kea'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'

import { warehouseProvisioningLogic } from './tabs/warehouseProvisioningLogic'

export function InitialPasswordBanner(): JSX.Element | null {
    const { initialPassword } = useValues(warehouseProvisioningLogic)
    const { clearInitialPassword } = useActions(warehouseProvisioningLogic)

    if (!initialPassword) {
        return null
    }

    return (
        <LemonBanner type="warning" onClose={clearInitialPassword}>
            <div className="space-y-2">
                <strong>Save your password now. It won't be shown again.</strong>
                <CodeSnippet compact thing="password" className="ph-no-capture ph-replay-block">
                    {initialPassword}
                </CodeSnippet>
            </div>
        </LemonBanner>
    )
}
