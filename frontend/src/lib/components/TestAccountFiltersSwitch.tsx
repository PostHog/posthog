import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonSwitchProps } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { sidePanelSettingsLogic } from '~/layout/navigation-3000/sidepanel/panels/sidePanelSettingsLogic'

type TestAccountFilterProps = Partial<LemonSwitchProps> & {
    checked: boolean
    onChange: (checked: boolean) => void
}

export function TestAccountFilterSwitch({ checked, onChange, ...props }: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const { openSettingsPanel } = useActions(sidePanelSettingsLogic)
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
                        onClick={() => openSettingsPanel({ settingId: 'internal-user-filtering' })}
                    />
                </div>
            }
        />
    )
}
