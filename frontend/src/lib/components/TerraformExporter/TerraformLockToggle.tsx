import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

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
                label={
                    <div className="flex gap-1 items-center">
                        <span>Lock access control to Terraform</span>
                        {lock !== null && (
                            <Tooltip title={lockDescription(lock)}>
                                <IconInfo className="text-secondary text-lg shrink-0" />
                            </Tooltip>
                        )}
                    </div>
                }
                checked={lock?.managed ?? false}
                onChange={setLock}
                loading={lockLoading}
                disabledReason={lock === null ? 'Loading…' : undefined}
                data-attr="access-control-terraform-lock"
            />
            {lock?.terraform_last_applied_at && (
                <p className="text-secondary text-xs mb-0">
                    <span>Last applied </span>
                    <TZLabel time={lock.terraform_last_applied_at} />
                </p>
            )}
        </div>
    )
}
