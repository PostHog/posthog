import { IconExternal } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { MaxInstance } from 'scenes/max/Max'
import { urls } from 'scenes/urls'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'

export function SidePanelMax(): JSX.Element {
    const { closeSidePanel } = useActions(sidePanelStateLogic)

    return (
        <>
            <SidePanelPaneHeader>
                <div className="flex-1" />
                <LemonButton
                    size="small"
                    sideIcon={<IconExternal />}
                    to={urls.max()}
                    onClick={() => closeSidePanel()}
                    tooltip="Open as main focus"
                    tooltipPlacement="bottom"
                />
            </SidePanelPaneHeader>
            <MaxInstance />
        </>
    )
}
