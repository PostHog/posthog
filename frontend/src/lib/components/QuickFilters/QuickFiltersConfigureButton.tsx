import { useActions } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { QuickFiltersLogicProps } from './quickFiltersLogic'
import { QuickFiltersModal } from './QuickFiltersModal'
import { quickFiltersModalLogic } from './quickFiltersModalLogic'

export function QuickFiltersConfigureButton({ context }: QuickFiltersLogicProps): JSX.Element {
    const { openModal } = useActions(quickFiltersModalLogic({ context }))

    return (
        <>
            <QuickFiltersModal context={context} />
            <LemonButton size="small" icon={<IconGear />} onClick={openModal} tooltip="Configure quick filters" />
        </>
    )
}
