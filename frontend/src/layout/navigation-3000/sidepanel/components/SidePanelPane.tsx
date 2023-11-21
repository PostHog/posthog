import { LemonButton, Tooltip } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { IconClose } from 'lib/lemon-ui/icons'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export function SidePanelPaneHeader({ children }: { children: React.ReactNode }): JSX.Element {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <header className="border-b flex-0 p-1 flex items-center justify-end gap-1 h-10">
            {children}
            <Tooltip placement="bottomRight" title="Close this side panel">
                <LemonButton size="small" sideIcon={<IconClose />} onClick={() => closeSidePanel()} />
            </Tooltip>
        </header>
    )
}
