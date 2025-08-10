import { useValues } from 'kea'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

import { HedgehogMode } from 'lib/components/HedgehogMode/HedgehogMode'

export function HedgehogButton(): JSX.Element | null {
    const { hedgehogModeEnabled } = useValues(toolbarLogic)

    return <HedgehogMode enabledOverride={hedgehogModeEnabled} />
}
