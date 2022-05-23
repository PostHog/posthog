import React, { useEffect } from 'react'
import './IngestionWizard.scss'
import '../authentication/bridgePagesShared.scss'

import { VerificationPanel } from 'scenes/ingestion/panels/VerificationPanel'
import { InstructionsPanel } from 'scenes/ingestion/panels/InstructionsPanel'
import { MOBILE, BACKEND, WEB, BOOKMARKLET, THIRD_PARTY } from 'scenes/ingestion/constants'
import { useValues, useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { FrameworkPanel } from 'scenes/ingestion/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/ingestion/panels/PlatformPanel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { BookmarkletPanel } from './panels/BookmarkletPanel'
import { ThirdPartyPanel } from './panels/ThirdPartyPanel'
import { Sidebar } from './Sidebar'
import { InviteModal } from 'scenes/organization/Settings/InviteModal'
import { inviteLogic } from 'scenes/organization/Settings/inviteLogic'
import { FriendlyLogo } from '~/toolbar/assets/FriendlyLogo'
import { SitePopover } from '~/layout/navigation/TopBar/SitePopover'

export const scene: SceneExport = {
    component: IngestionWizard,
    logic: ingestionLogic,
}

export function IngestionWizard(): JSX.Element {
    const { platform, framework, verify } = useValues(ingestionLogic)
    const { reportIngestionLandingSeen } = useActions(eventUsageLogic)

    useEffect(() => {
        if (!platform) {
            reportIngestionLandingSeen()
        }
    }, [platform])

    if (!platform && !verify) {
        return (
            <IngestionContainer>
                <PlatformPanel />
            </IngestionContainer>
        )
    }

    if (verify) {
        return (
            <IngestionContainer>
                <VerificationPanel />
            </IngestionContainer>
        )
    }

    if (framework || platform === WEB) {
        return (
            <IngestionContainer>
                <InstructionsPanel />
            </IngestionContainer>
        )
    }

    if (platform === MOBILE || platform === BACKEND) {
        return (
            <IngestionContainer>
                <FrameworkPanel />
            </IngestionContainer>
        )
    }

    if (platform === BOOKMARKLET) {
        return (
            <IngestionContainer>
                <BookmarkletPanel />
            </IngestionContainer>
        )
    }

    if (platform === THIRD_PARTY) {
        return (
            <IngestionContainer>
                <ThirdPartyPanel />
            </IngestionContainer>
        )
    }

    return <></>
}

function IngestionContainer({ children }: { children: React.ReactNode }): JSX.Element {
    const { isInviteModalShown } = useValues(inviteLogic)
    const { hideInviteModal } = useActions(inviteLogic)
    const { onboardingSidebar } = useValues(ingestionLogic)

    return (
        <div style={{ display: 'flex', height: '100%' }}>
            {onboardingSidebar && (
                <>
                    <InviteModal visible={isInviteModalShown} onClose={hideInviteModal} />
                    <Sidebar />
                </>
            )}
            <div className="bridge-page IngestionContainer">
                {!onboardingSidebar && (
                    <div className="mb">
                        <FriendlyLogo />
                    </div>
                )}
                {children}
            </div>
            {onboardingSidebar && (
                <div style={{ position: 'fixed', right: 0, marginRight: '1rem' }}>
                    <SitePopover />
                </div>
            )}
        </div>
    )
}
