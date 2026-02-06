import { useValues } from 'kea'

import { HedgehogMode } from 'lib/components/HedgehogMode/HedgehogMode'

import { toolbarLogic } from '~/toolbar/bar/toolbarLogic'

export function HedgehogButton(): JSX.Element | null {
    const { hedgehogModeEnabled } = useValues(toolbarLogic)

    return <HedgehogMode enabledOverride={hedgehogModeEnabled} />
}
