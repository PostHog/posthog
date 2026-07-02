import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { navigationLogic } from '../navigationLogic'

export function ZenModeButton(): JSX.Element | null {
    const { zenMode } = useValues(navigationLogic)
    const { setZenMode } = useActions(navigationLogic)

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
