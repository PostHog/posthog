import { useEffect, useRef, useState } from 'react'
import './IngestionWizard.scss'

import { VerificationPanel } from 'scenes/ingestion/v2/panels/VerificationPanel'
import { InstructionsPanel } from 'scenes/ingestion/v2/panels/InstructionsPanel'
import { useValues, useActions } from 'kea'
import { ingestionLogicV2, INGESTION_VIEWS } from 'scenes/ingestion/v2/ingestionLogicV2'
import { FrameworkPanel } from 'scenes/ingestion/v2/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/ingestion/v2/panels/PlatformPanel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { GeneratingDemoDataPanel } from './panels/GeneratingDemoDataPanel'
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
import { NoDemoIngestionPanel } from './panels/NoDemoIngestionPanel'

export function IngestionWizardV2(): JSX.Element {
    const { currentView, platform } = useValues(ingestionLogicV2)
    const { reportIngestionLandingSeen, reportIngestionWait } = useActions(eventUsageLogic)

    const [minutesPassed, setMinutesPassed] = useState(0)
    const timeout = useRef(0)

    useEffect(() => {
        if (!platform) {
            reportIngestionLandingSeen()
        }
    }, [platform])

    useEffect(() => {
        timeout.current = window.setTimeout(() => {
            reportIngestionWait(minutesPassed + 1)
            setMinutesPassed(minutesPassed + 1)
        }, 1000)
        return () => {
            window.clearTimeout(timeout.current)
        }
    }, [minutesPassed])

    return (
        <IngestionContainer>
            {currentView === INGESTION_VIEWS.BILLING && <BillingPanel />}
            {currentView === INGESTION_VIEWS.INVITE_TEAM && <InviteTeamPanel />}
            {currentView === INGESTION_VIEWS.TEAM_INVITED && <TeamInvitedPanel />}
            {currentView === INGESTION_VIEWS.CHOOSE_PLATFORM && <PlatformPanel />}
            {currentView === INGESTION_VIEWS.CHOOSE_FRAMEWORK && <FrameworkPanel />}
            {currentView === INGESTION_VIEWS.WEB_INSTRUCTIONS && <InstructionsPanel />}
            {currentView === INGESTION_VIEWS.VERIFICATION && <VerificationPanel />}
            {currentView === INGESTION_VIEWS.GENERATING_DEMO_DATA && <GeneratingDemoDataPanel />}
            {currentView === INGESTION_VIEWS.CHOOSE_THIRD_PARTY && <ThirdPartyPanel />}
            {currentView === INGESTION_VIEWS.NO_DEMO_INGESTION && <NoDemoIngestionPanel />}
        </IngestionContainer>
    )
}

function IngestionContainer({ children }: { children: React.ReactNode }): JSX.Element {
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { isSmallScreen } = useValues(ingestionLogicV2)

    return (
        <div className="flex h-full flex-col">
            <div className="IngestionTopbar">
                <FriendlyLogo style={{ fontSize: '1.125rem' }} />
                <div className="flex">
                    <HelpButton />
                    <SitePopover />
                </div>
            </div>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
            <div className="flex h-full">
                {!isSmallScreen && <Sidebar />}
                {/* <div className="IngestionContainer" */}
                <BridgePage
                    view="ingestion"
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
