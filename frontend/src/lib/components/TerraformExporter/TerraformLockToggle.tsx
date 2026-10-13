import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { AccessControlManagementApi } from 'products/access_control/frontend/generated/api.schemas'

import { TerraformLockLogicProps, terraformLockLogic } from './terraformLockLogic'

function lockDescription(lock: AccessControlManagementApi): string {
    if (!lock.managed) {
        return 'Access rules in this project can be changed here. The next Terraform apply that changes a rule turns the lock back on.'
    }
    if (!lock.has_terraform_account) {
        return 'Nobody can change access rules in this project until Terraform applies them for the first time.'
    }
    return 'Only Terraform can change access rules in this project.'
}

/** Switch at the top of the access control export that locks the project's access rules to Terraform */
export function TerraformLockToggle(props: TerraformLockLogicProps): JSX.Element {
    const logic = terraformLockLogic(props)
    const { lock, lockLoading } = useValues(logic)
    const { setLock } = useActions(logic)

    return (
        <div className="space-y-1">
            <LemonSwitch
                bordered
                fullWidth
                label="Lock access control to Terraform"
                checked={lock?.managed ?? false}
                onChange={setLock}
                loading={lockLoading}
                disabledReason={lock === null ? 'Loading…' : undefined}
                data-attr="access-control-terraform-lock"
            />
            {lock !== null && (
                <p className="text-secondary text-xs mb-0">
                    <span>{lockDescription(lock)}</span>
                    {lock.terraform_last_applied_at && (
                        <span>
                            {' '}
                            Last applied <TZLabel time={lock.terraform_last_applied_at} />.
                        </span>
                    )}
                </p>
            )}
        </div>
    )
}
