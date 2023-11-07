import { useEffect } from 'react'
import './IngestionWizard.scss'

import { VerificationPanel } from 'scenes/ingestion/panels/VerificationPanel'
import { InstructionsPanel } from 'scenes/ingestion/panels/InstructionsPanel'
import { useValues, useActions } from 'kea'
import { ingestionLogic, INGESTION_VIEWS } from 'scenes/ingestion/ingestionLogic'
import { FrameworkPanel } from 'scenes/ingestion/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/ingestion/panels/PlatformPanel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { GeneratingDemoDataPanel } from './panels/GeneratingDemoDataPanel'
import { ThirdPartyPanel } from './panels/ThirdPartyPanel'
import { BillingPanel } from './panels/BillingPanel'
import { Sidebar } from './Sidebar'
import { InviteModal } from 'scenes/organization/Settings/InviteModal'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { Logo } from '~/toolbar/assets/Logo'
import { SitePopover } from '~/layout/navigation/TopBar/SitePopover'
import { HelpButton } from 'lib/components/HelpButton/HelpButton'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { PanelHeader } from './panels/PanelComponents'
import { InviteTeamPanel } from './panels/InviteTeamPanel'
import { TeamInvitedPanel } from './panels/TeamInvitedPanel'
import { NoDemoIngestionPanel } from './panels/NoDemoIngestionPanel'
import { SuperpowersPanel } from 'scenes/ingestion/panels/SuperpowersPanel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export function IngestionWizard(): JSX.Element {
    const { currentView, platform } = useValues(ingestionLogic)
    const { reportIngestionLandingSeen } = useActions(eventUsageLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    useEffect(() => {
        if (!platform) {
            reportIngestionLandingSeen()
        }
    }, [platform])

    if (featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] === 'test') {
        router.actions.replace(urls.products())
    }

    return (
        <IngestionContainer>
            {currentView === INGESTION_VIEWS.BILLING && <BillingPanel />}
            {currentView === INGESTION_VIEWS.SUPERPOWERS && <SuperpowersPanel />}
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
    const { isSmallScreen } = useValues(ingestionLogic)

    return (
        <div className="flex flex-col h-screen overflow-hidden">
            <div className="IngestionTopbar">
                <Logo style={{ fontSize: '1.125rem' }} />
                <div className="flex">
                    <HelpButton />
                    <SitePopover />
                </div>
            </div>
            <div className="flex h-full">
                {!isSmallScreen && <Sidebar />}
                {/* <div className="IngestionContainer" */}
                <BridgePage
                    view="ingestion"
                    noLogo
                    fixedWidth={false}
                    header={<PanelHeader />}
                    className="IngestionContent h-full"
                    fullScreen={false}
                >
                    {children}
                </BridgePage>
            </div>
            <InviteModal isOpen={isInviteModalShown} onClose={hideInviteModal} />
        </div>
    )
}
