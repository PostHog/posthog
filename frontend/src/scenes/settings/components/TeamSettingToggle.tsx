import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { TeamType } from '~/types'

import { teamSettingToggleLogic } from './teamSettingToggleLogic'

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
    const logic = teamSettingToggleLogic({ field, label })
    const { setValue } = useActions(logic)
    const { checked: rawChecked, isSaving } = useValues(logic)

    const displayChecked = invert ? !rawChecked : rawChecked

    return (
        <LemonSwitch
            onChange={(checked) => {
                const newValue = invert ? !checked : checked
                setValue(newValue)
                onChange?.(checked)
            }}
            checked={displayChecked}
            loading={isSaving}
            disabledReason={disabledReason}
            label={label}
            bordered
        />
    )
}
