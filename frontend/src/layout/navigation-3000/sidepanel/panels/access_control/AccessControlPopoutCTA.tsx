import { useActions } from 'kea'

import { IconOpenSidebar } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { captureAccessControlEvent } from 'lib/utils/accessControlUtils'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AccessControlResourceType, SidePanelTab } from '~/types'

interface AccessControlPopoutCTAProps {
    callback?: () => void
    resourceType: AccessControlResourceType
}

export const AccessControlPopoutCTA = ({ callback, resourceType }: AccessControlPopoutCTAProps): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)

    return (
        <div>
            <h3>Access control</h3>
            <LemonButton
                type="primary"
                icon={<IconOpenSidebar />}
                onClick={() => {
                    captureAccessControlEvent('access control popout cta clicked', { resourceType })
                    openSidePanel(SidePanelTab.AccessControl)
                    callback?.()
                }}
            >
                Open access control
            </LemonButton>
        </div>
    )
}
