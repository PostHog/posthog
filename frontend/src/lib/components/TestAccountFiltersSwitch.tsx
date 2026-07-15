import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, LemonSwitchProps } from '@posthog/lemon-ui'

import { Link } from 'lib/lemon-ui/Link'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

const NO_FILTERS_REASON = "You haven't set any internal test filters. Click the gear icon to configure."

type TestAccountFilterProps = Partial<LemonSwitchProps> & {
    checked: boolean
    onChange: (checked: boolean) => void
    /**
     * When there are no test-account filters the switch is disabled, and by default the reason only
     * shows on hover. Set this to also surface the reason as visible text below the switch, so on
     * surfaces where the tooltip is easy to miss the control doesn't read as broken.
     */
    explainWhenNoFilters?: boolean
}

export function TestAccountFilterSwitch({
    checked,
    onChange,
    explainWhenNoFilters,
    ...props
}: TestAccountFilterProps): JSX.Element | null {
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const filtersSettingsUrl = urls.settings('project-product-analytics', 'internal-user-filtering')
    const lemonSwitch = (
        <LemonSwitch
            id="test-account-filter"
            bordered
            {...props}
            disabledReason={!hasFilters ? NO_FILTERS_REASON : props.disabledReason}
            checked={checked}
            onChange={onChange}
            label={
                <div className="flex items-center">
                    <span>Filter out internal and test users</span>
                    <LemonButton icon={<IconGear />} size="small" noPadding className="ml-1" to={filtersSettingsUrl} />
                </div>
            }
        />
    )

    if (explainWhenNoFilters && !hasFilters) {
        return (
            <div className="flex flex-col items-end gap-1">
                {lemonSwitch}
                <span className="text-xs text-muted text-right">
                    You haven't set any internal test filters yet. <Link to={filtersSettingsUrl}>Configure them</Link>{' '}
                    to enable this.
                </span>
            </div>
        )
    }

    return lemonSwitch
}
