import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { navigation3000Logic } from '../navigationLogic'

export function ZenModeButton(): JSX.Element | null {
    const { zenMode } = useValues(navigation3000Logic)
    const { setZenMode } = useActions(navigation3000Logic)

    if (!zenMode) {
        return null
    }

    return (
        <LemonButton
            type="secondary"
            size="small"
            icon={<IconX />}
            onClick={() => setZenMode(false)}
            tooltip="Exit zen mode"
        >
            Exit zen mode
        </LemonButton>
    )
}
