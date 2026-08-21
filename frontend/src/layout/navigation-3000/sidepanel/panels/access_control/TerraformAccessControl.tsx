import { useActions, useValues } from 'kea'

import { LemonSwitch, Link } from '@posthog/lemon-ui'

import { terraformAccessControlLogic } from './terraformAccessControlLogic'

// This setting owns its heading rather than declaring one in the settings map. The map renders a
// setting's title and description around its component, so a map-declared heading would sit on the
// page on its own for every environment that has never used Terraform.
export function TerraformAccessControl(): JSX.Element | null {
    const { settings, settingsLoading, shouldShowSetting } = useValues(terraformAccessControlLogic)
    const { setLock } = useActions(terraformAccessControlLogic)

    if (!shouldShowSetting) {
        return null
    }

    return (
        <div>
            <h2 id="environment-access-control-terraform" className="text-base font-semibold mb-0">
                Terraform-managed rules
            </h2>
            <p className="max-w-160 text-sm text-secondary mb-4">
                Editing a rule here that Terraform manages does not last. The next apply puts the rule back. Turn this
                on to have PostHog refuse those changes instead.{' '}
                <Link
                    to="https://posthog.com/docs/settings/access-control"
                    target="_blank"
                    data-attr="settings-docs-link-environment-access-control-terraform"
                >
                    Docs
                </Link>
            </p>
            <LemonSwitch
                bordered
                id="lock-terraform-managed-rules"
                label="Only let Terraform change the rules it manages"
                checked={!!settings?.lock_terraform_managed_rules}
                disabledReason={settingsLoading ? 'Saving…' : undefined}
                onChange={(checked) => setLock(checked)}
            />
        </div>
    )
}
