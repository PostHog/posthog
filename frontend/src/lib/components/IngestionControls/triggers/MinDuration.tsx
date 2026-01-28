import { useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { SESSION_REPLAY_MINIMUM_DURATION_OPTIONS } from 'lib/constants'

import { AccessControlLevel } from '~/types'

import { ingestionControlsLogic } from '../ingestionControlsLogic'

export function MinDurationTrigger({
    value,
    onChange,
}: {
    value: number | null | undefined
    onChange: (value: number | null | undefined) => void
}): JSX.Element {
    const { resourceType } = useValues(ingestionControlsLogic)

    return (
        <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
            <LemonSelect
                dropdownMatchSelectWidth={false}
                onChange={onChange}
                options={SESSION_REPLAY_MINIMUM_DURATION_OPTIONS}
                value={value}
            />
        </AccessControlAction>
    )
}
