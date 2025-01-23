import { IconOpenSidebar } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

export const AccessControlPopoutCTA = ({ callback }: { callback?: () => void }): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div>
            <h3>Access control</h3>
            <LemonBanner type="info" className="mb-4">
                Permissions are moving. We're rolling out our new access control system. Click below to open it.
            </LemonBanner>
            <LemonButton
                type="primary"
                icon={<IconOpenSidebar />}
                onClick={() => {
                    openSidePanel(SidePanelTab.AccessControl)
                    callback?.()
                }}
            >
                Open access control
            </LemonButton>
        </div>
    )
}
