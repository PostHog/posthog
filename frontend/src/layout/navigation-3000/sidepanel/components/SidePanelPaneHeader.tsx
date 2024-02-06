import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'

import { sidePanelStateLogic } from '../sidePanelStateLogic'

export type SidePanelPaneHeaderProps = {
    title?: string | JSX.Element
    children?: React.ReactNode
}

export function SidePanelPaneHeader({ children, title }: SidePanelPaneHeaderProps): JSX.Element {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <header className="border-b shrink-0 p-1 flex items-center justify-end gap-1 h-10">
            {title ? (
                <h4 className="flex-1 flex items-center gap-1 font-semibold px-2 mb-0 truncate">{title}</h4>
            ) : null}
            {children}
            <Tooltip placement="bottom-end" title="Close this side panel">
                <LemonButton size="small" sideIcon={<IconClose />} onClick={() => closeSidePanel()} />
            </Tooltip>
        </header>
    )
}
