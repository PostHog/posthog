import { useValues } from 'kea'

import { IconExternal, IconGear } from '@posthog/icons'
import { Button, Field, FieldLabel, Switch } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { getTestAccountFilterSwitchDisabledReason, type TestAccountFilterProps } from './TestAccountFiltersSwitch'

export type QuillTestAccountFilterSwitchProps = Pick<
    TestAccountFilterProps,
    'checked' | 'onChange' | 'applicableFilterTypes' | 'onConfigure' | 'settingsLinkIcon' | 'disabledReason'
> & {
    id?: string
    'data-attr'?: string
}

export function QuillTestAccountFilterSwitch({
    checked,
    onChange,
    applicableFilterTypes,
    onConfigure,
    settingsLinkIcon = 'gear',
    disabledReason,
    id = 'test-account-filter',
    'data-attr': dataAttr,
}: QuillTestAccountFilterSwitchProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const showNewTabIcon = settingsLinkIcon === 'new-tab' && !onConfigure
    const settingsIcon = showNewTabIcon ? <IconExternal /> : <IconGear />

    return (
        <Field orientation="horizontal" className="min-h-6">
            <Switch
                id={id}
                size="sm"
                checked={checked}
                onCheckedChange={(next: boolean) => onChange(next)}
                disabledReason={getTestAccountFilterSwitchDisabledReason({
                    filters: currentTeam?.test_account_filters || [],
                    applicableFilterTypes,
                    disabledReason,
                    showNewTabIcon,
                })}
                data-attr={dataAttr}
            />
            <div className="flex min-w-0 items-center gap-1">
                <FieldLabel htmlFor={id} className="font-normal">
                    Filter out internal and test users
                </FieldLabel>
                {onConfigure ? (
                    <Button
                        size="icon-xs"
                        aria-label="Configure internal and test users"
                        tooltip="Configure internal and test users."
                        onClick={onConfigure}
                    >
                        {settingsIcon}
                    </Button>
                ) : (
                    <Button
                        size="icon-xs"
                        aria-label="Configure internal and test users"
                        tooltip="Configure internal and test users. Opens in a new tab."
                        render={
                            <LinkPrimitive
                                to={urls.settings('environment-customization', 'internal-user-filtering')}
                                target="_blank"
                            />
                        }
                    >
                        {settingsIcon}
                    </Button>
                )}
            </div>
        </Field>
    )
}
