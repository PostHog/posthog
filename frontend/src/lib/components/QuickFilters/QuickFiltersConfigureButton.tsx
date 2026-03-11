import { useActions } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { QuickFiltersModal } from './QuickFiltersModal'
import { QuickFiltersModalLogicProps, quickFiltersModalLogic } from './quickFiltersModalLogic'

interface QuickFiltersConfigureButtonProps extends QuickFiltersModalLogicProps {
    /** Show a text label alongside the icon (useful when no filters exist yet) */
    showLabel?: boolean
}

export function QuickFiltersConfigureButton({
    context,
    onNewFilterCreated,
    showLabel,
}: QuickFiltersConfigureButtonProps): JSX.Element {
    const logicProps = { context, onNewFilterCreated }
    const { openModal } = useActions(quickFiltersModalLogic(logicProps))

    return (
        <>
            <QuickFiltersModal {...logicProps} />
            <LemonButton size="small" icon={<IconGear />} onClick={openModal} tooltip="Configure quick filters">
                {showLabel ? 'Configure quick filters' : undefined}
            </LemonButton>
        </>
    )
}
