import { useActions, useValues } from 'kea'

import { IconOpenSidebar } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { captureAccessControlEvent, resourceTypeToString } from 'lib/utils/accessControlUtils'
import { toSentenceCase } from 'lib/utils/strings'

import { sidePanelLogic } from '~/layout/navigation-3000/sidepanel/sidePanelLogic'
import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { AccessControlResourceType, SidePanelTab } from '~/types'

interface AccessControlPopoutCTAProps {
    callback?: () => void
    resourceType: AccessControlResourceType
}

export const AccessControlPopoutCTA = ({ callback, resourceType }: AccessControlPopoutCTAProps): JSX.Element => {
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { enabledTabs } = useValues(sidePanelLogic)

    // The access control panel only renders once the scene supplies its resource context. Opening it
    // before then paints an empty panel, so gate the button on the tab actually being available.
    const accessControlAvailable = enabledTabs.includes(SidePanelTab.AccessControl)

    return (
        <div>
            <h3>Access control</h3>
            <LemonBanner type="info" className="mb-4">
                {toSentenceCase(resourceTypeToString(resourceType))} permissions are moving. We're rolling out our new
                access control system. Click below to open it.
            </LemonBanner>
            <LemonButton
                type="primary"
                icon={<IconOpenSidebar />}
                disabledReason={
                    accessControlAvailable ? undefined : 'Access control is still loading. Try again in a moment.'
                }
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
