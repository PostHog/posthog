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
import posthogLogo from 'public/posthog-logo.png'
import { ThirdPartyPanel } from './panels/ThirdPartyPanel'

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

    if (!platform) {
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
    return (
        <div className="bridge-page IngestionContainer">
            <div className="mb">
                <img src={posthogLogo} style={{ width: 157, height: 30 }} />
            </div>
            {children}
        </div>
    )
}
