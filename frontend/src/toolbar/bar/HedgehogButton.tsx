import { useValues } from 'kea'

import { HedgehogMode } from 'lib/components/HedgehogMode/HedgehogMode'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

export function HedgehogButton(): JSX.Element | null {
    const { hedgehogModeEnabled, hedgehogModeAvailable } = useValues(toolbarLogic)

    if (!hedgehogModeAvailable) {
        return null
    }

    return <HedgehogMode enabledOverride={hedgehogModeEnabled} />
}
