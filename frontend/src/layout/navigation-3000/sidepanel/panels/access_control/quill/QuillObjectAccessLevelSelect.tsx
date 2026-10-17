import { useValues } from 'kea'

import { AccessControlLevel } from '~/types'

import { InheritedAccess, accessControlLogic } from '../accessControlLogic'
import { QuillAccessLevelSelect } from './QuillAccessLevelSelect'

interface QuillObjectAccessLevelSelectProps {
    level: AccessControlLevel | null
    levels: AccessControlLevel[]
    onChange: (newValue: AccessControlLevel | null) => void
    disabled?: boolean
    disabledReason?: string
    /**
     * What applies once the rule is removed. Passing it offers "No override" as a way back, so
     * only the object default sets it. Member and role rows are removed with their own button.
     */
    inherited?: InheritedAccess | null
}

export function QuillObjectAccessLevelSelect(props: QuillObjectAccessLevelSelectProps): JSX.Element {
    const { canEditAccessControls, minimumAccessLevel } = useValues(accessControlLogic)

    return (
        <QuillAccessLevelSelect
            level={props.level}
            levels={props.levels}
            onChange={props.onChange}
            // The permission gate wins over any caller-supplied reason, so a reason passed for
            // some other purpose can never re-enable the control for someone who cannot edit
            disabledReason={!canEditAccessControls || props.disabled ? 'You cannot edit this' : props.disabledReason}
            minimumLevel={minimumAccessLevel}
            inherited={props.inherited}
        />
    )
}
