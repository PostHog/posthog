import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { TeamType } from '~/types'

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

    const rawValue = !!currentTeam?.[field]
    const displayChecked = invert ? !rawValue : rawValue

    return (
        <LemonSwitch
            onChange={(checked) => {
                const newValue = invert ? !checked : checked
                updateCurrentTeam({ [field]: newValue })
                onChange?.(checked)
            }}
            checked={displayChecked}
            disabled={currentTeamLoading}
            disabledReason={disabledReason}
            label={label}
            bordered
        />
    )
}
