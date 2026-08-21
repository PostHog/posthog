import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { terraformAccessControlLogic } from './terraformAccessControlLogic'

export function TerraformAccessControl(): JSX.Element | null {
    const { settings, settingsLoading, shouldShowSetting } = useValues(terraformAccessControlLogic)
    const { setLock } = useActions(terraformAccessControlLogic)

    if (!shouldShowSetting) {
        return null
    }

    return (
        <div className="deprecated-space-y-2">
            <LemonSwitch
                bordered
                id="lock-terraform-managed-rules"
                label="Only let Terraform change the rules it manages"
                checked={!!settings?.lock_terraform_managed_rules}
                disabledReason={settingsLoading ? 'Saving…' : undefined}
                onChange={(checked) => setLock(checked)}
            />
            <p className="text-secondary mb-0">
                Editing a rule here that Terraform manages does not last. The next apply puts the rule back. Turn this
                on to have PostHog refuse those changes instead.
            </p>
        </div>
    )
}
