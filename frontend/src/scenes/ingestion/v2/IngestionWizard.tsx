import { useEffect } from 'react'
import './IngestionWizard.scss'

import { VerificationPanel } from 'scenes/ingestion/v2/panels/VerificationPanel'
import { InstructionsPanel } from 'scenes/ingestion/v2/panels/InstructionsPanel'
import { useValues, useActions } from 'kea'
import { ingestionLogicV2, INGESTION_VIEWS } from 'scenes/ingestion/v2/ingestionLogic'
import { FrameworkPanel } from 'scenes/ingestion/v2/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/ingestion/v2/panels/PlatformPanel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BookmarkletPanel } from './panels/BookmarkletPanel'
import { ThirdPartyPanel } from './panels/ThirdPartyPanel'
import { BillingPanel } from './panels/BillingPanel'
import { Sidebar } from './Sidebar'
import { InviteModal } from 'scenes/organization/Settings/InviteModal'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import { SitePopover } from '~/layout/navigation/TopBar/SitePopover'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { PanelHeader } from './panels/PanelComponents'
import { InviteTeamPanel } from './panels/InviteTeamPanel'
import { TeamInvitedPanel } from './panels/TeamInvitedPanel'

export function IngestionWizardV2(): JSX.Element {
    const { currentView, platform } = useValues(ingestionLogicV2)
    const { reportIngestionLandingSeen } = useActions(eventUsageLogic)

    useEffect(() => {
        if (!platform) {
            reportIngestionLandingSeen()
        }
    }, [platform])

    return (
        <IngestionContainer>
            {currentView === INGESTION_VIEWS.BILLING && <BillingPanel />}
            {currentView === INGESTION_VIEWS.INVITE_TEAM && <InviteTeamPanel />}
            {currentView === INGESTION_VIEWS.TEAM_INVITED && <TeamInvitedPanel />}
            {currentView === INGESTION_VIEWS.CHOOSE_PLATFORM && <PlatformPanel />}
            {currentView === INGESTION_VIEWS.CHOOSE_FRAMEWORK && <FrameworkPanel />}
            {currentView === INGESTION_VIEWS.WEB_INSTRUCTIONS && <InstructionsPanel />}
            {currentView === INGESTION_VIEWS.VERIFICATION && <VerificationPanel />}
            {currentView === INGESTION_VIEWS.BOOKMARKLET && <BookmarkletPanel />}
            {currentView === INGESTION_VIEWS.CHOOSE_THIRD_PARTY && <ThirdPartyPanel />}
        </IngestionContainer>
    )
}

function IngestionContainer({ children }: { children: React.ReactNode }): JSX.Element {
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { isSmallScreen, hasInvitedMembers } = useValues(ingestionLogicV2)
    const { next } = useActions(ingestionLogicV2)

    return (
        <div className="flex h-full flex-col">
            <div className="IngestionTopbar">
                <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                <div className="flex">
                    <HelpButton />
                    <SitePopover />
                </div>
            </div>
            <InviteModal
                isOpen={isInviteModalShown}
                onClose={() => {
                    hideInviteModal()
                    if (hasInvitedMembers) {
                        next({ isTechnicalUser: false })
                    }
                }}
            />
            <div className="flex h-full">
                {!isSmallScreen && <Sidebar />}
                {/* <div className="IngestionContainer" */}
                <BridgePage
                    view="ingestion"
                    noHedgehog
                    noLogo
                    fixedWidth={false}
                    header={<PanelHeader />}
                    className="IngestionContent"
                >
                    {children}
                </BridgePage>
            </div>
        </div>
    )
}
