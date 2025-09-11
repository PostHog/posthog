import { useActions } from 'kea'
import posthog from 'posthog-js'

import { IconOpenSidebar } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { resourceTypeToString } from 'lib/components/AccessControlAction'
import { toSentenceCase } from 'lib/utils'

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
            <LemonBanner type="info" className="mb-4">
                {toSentenceCase(resourceTypeToString(resourceType))} permissions are moving. We're rolling out our new
                access control system. Click below to open it.
            </LemonBanner>
            <LemonButton
                type="primary"
                icon={<IconOpenSidebar />}
                onClick={() => {
                    posthog.capture('access control popout cta clicked', { resourceType })
                    openSidePanel(SidePanelTab.AccessControl)
                    callback?.()
                }}
            >
                Open access control
            </LemonButton>
        </div>
    )
}
