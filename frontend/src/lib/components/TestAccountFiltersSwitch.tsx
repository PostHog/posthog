import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonSwitchProps, Link } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

type TestAccountFilterProps = Partial<LemonSwitchProps> & {
    checked: boolean | 'indeterminate'
    onChange: (checked: boolean) => void
    /**
     * Opt-in override semantics: while `checked` is `'indeterminate'` (no explicit choice, falling back to the
     * project default) a "No override set" hint is shown; once an explicit value exists, an "Unset override"
     * link calls this to clear it.
     */
    onReset?: () => void
}

export function TestAccountFilterSwitch({
    checked,
    onChange,
    onReset,
    ...props
}: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    return (
        <LemonSwitch
            id="test-account-filter"
            bordered
            {...props}
            disabledReason={
                !hasFilters
                    ? "You haven't set any internal test filters. Click the gear icon to configure."
                    : props.disabledReason
            }
            checked={checked}
            onChange={onChange}
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton
                        icon={<IconGear />}
                        size="small"
                        noPadding
                        className="ml-1"
                        to={urls.settings('project-product-analytics', 'internal-user-filtering')}
                    />
                    {onReset &&
                        (checked === 'indeterminate' ? (
                            <span className="ml-1 text-xs text-tertiary">No override set</span>
                        ) : (
                            <Link
                                className="ml-1 text-xs"
                                onClick={(e) => {
                                    e.preventDefault()
                                    e.stopPropagation()
                                    onReset()
                                }}
                            >
                                Unset override
                            </Link>
                        ))}
                </div>
            }
        />
    )
}
