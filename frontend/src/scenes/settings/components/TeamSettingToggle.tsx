import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

import { QuillSettingSwitch } from './QuillSettingSwitch'

export function TeamSettingToggle({
    field,
    label,
    invert,
    onChange,
    disabledReason,
}: {
    field: keyof TeamType
    label: string
    /** When true, the toggle shows as ON when the field is false (e.g. autocapture_opt_out) */
    invert?: boolean
    /** Optional callback after the team is updated */
    onChange?: (checked: boolean) => void
    disabledReason?: string | null
}): JSX.Element {
    const { updateCurrentTeam } = useActions(teamLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const rawValue = !!currentTeam?.[field]
    const displayChecked = invert ? !rawValue : rawValue

    const handleChange = (checked: boolean): void => {
        const newValue = invert ? !checked : checked
        updateCurrentTeam({ [field]: newValue })
        onChange?.(checked)
    }

    if (todayRailNav) {
        return (
            <QuillSettingSwitch
                label={label}
                checked={displayChecked}
                onCheckedChange={handleChange}
                disabled={currentTeamLoading}
                disabledReason={disabledReason}
            />
        )
    }

    return (
        <LemonSwitch
            onChange={handleChange}
            checked={displayChecked}
            disabled={currentTeamLoading}
            disabledReason={disabledReason}
            label={label}
            bordered
        />
    )
}
