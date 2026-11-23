import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconInfo } from '@posthog/icons'
import { Button, Field, FieldLabel, Switch, Text, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'

import { TerraformLockLogicProps, terraformLockLogic } from './terraformLockLogic'
import { lockDescription } from './TerraformLockToggle'

export function QuillTerraformLockToggle(props: TerraformLockLogicProps): JSX.Element {
    const logic = terraformLockLogic(props)
    const { lock, lockLoading } = useValues(logic)
    const { setLock } = useActions(logic)
    const switchId = useId()

    return (
        <div className="flex flex-col gap-1">
            <Field orientation="horizontal" className="w-fit">
                <Switch
                    id={switchId}
                    checked={lock?.managed ?? false}
                    onCheckedChange={setLock}
                    disabledReason={lock === null ? 'Loading…' : lockLoading ? 'Saving…' : undefined}
                    data-attr="access-control-terraform-lock"
                />
                <FieldLabel htmlFor={switchId}>Lock access control to Terraform</FieldLabel>
                {lock !== null && (
                    <Tooltip>
                        <TooltipTrigger delay={0} render={<Button size="icon-xs" aria-label="More information" />}>
                            <IconInfo />
                        </TooltipTrigger>
                        <TooltipContent className="max-w-80">{lockDescription(lock)}</TooltipContent>
                    </Tooltip>
                )}
            </Field>
            {lock?.terraform_last_applied_at && (
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    <span>Last applied </span>
                    <TZLabel time={lock.terraform_last_applied_at} />
                </Text>
            )}
        </div>
    )
}
