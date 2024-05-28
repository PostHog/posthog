import { IconGear } from '@posthog/icons'
import { LemonButtonWithDropdown, LemonSwitch, LemonSwitchProps } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Settings } from 'scenes/settings/Settings'
import { teamLogic } from 'scenes/teamLogic'

type TestAccountFilterProps = Partial<LemonSwitchProps> & {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function TestAccountFilterSwitch({ checked, onChange, ...props }: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0

    return (
        <LemonSwitch
            id="test-account-filter"
            bordered
            disabledReason={!hasFilters ? "You haven't set any internal test filters" : null}
            {...props}
            checked={checked}
            onChange={onChange}
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButtonWithDropdown
                        icon={<IconGear />}
                        size="small"
                        noPadding
                        className="ml-1"
                        dropdown={{
                            showArrow: true,
                            placement: 'top',
                            fallbackPlacements: ['bottom'],
                            closeOnClickInside: false,
                            overlay: (
                                <div className="p-2 max-w-120">
                                    <Settings
                                        hideSections
                                        logicKey="test-account-filter"
                                        settingId="internal-user-filtering"
                                    />
                                </div>
                            ),
                        }}
                    />
                </div>
            }
        />
    )
}
