import React from 'react'
import './IngestionWizard.scss'

import { VerificationPanel } from 'scenes/ingestion/panels/VerificationPanel'
import { AutocapturePanel } from 'scenes/ingestion/panels/AutocapturePanel'
import { InstructionsPanel } from 'scenes/ingestion/panels/InstructionsPanel'
import { MOBILE, BACKEND, WEB, BOOKMARKLET } from 'scenes/ingestion/constants'
import { useValues, useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { FrameworkPanel } from 'scenes/ingestion/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/ingestion/panels/PlatformPanel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { BookmarkletPanel } from './panels/BookmarkletPanel'
import posthogLogo from 'public/posthog-logo.png'

export const scene: SceneExport = {
    component: IngestionWizard,
    logic: ingestionLogic,
}

export function IngestionWizard(): JSX.Element {
    const { platform, framework, verify } = useValues(ingestionLogic)
    const { reportIngestionLandingSeen } = useActions(eventUsageLogic)

    if (verify) {
        return (
            <IngestionContainer>
                <VerificationPanel />
            </IngestionContainer>
        )
    }

    if (framework && platform !== WEB) {
        return (
            <IngestionContainer>
                <InstructionsPanel />
            </IngestionContainer>
        )
    }

    if (!platform) {
        reportIngestionLandingSeen(false)
        return (
            <IngestionContainer>
                <PlatformPanel />
            </IngestionContainer>
        )
    }

    if (platform === WEB) {
        return (
            <IngestionContainer>
                <AutocapturePanel />
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

    return <></>
}

function IngestionContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="background"
            style={{
                display: 'flex',
                width: '100vw',
                height: '100%',
                alignItems: 'center',
                justifyContent: 'flex-start',
                flexDirection: 'column',
                paddingTop: '2rem',
            }}
        >
            <div className="mb">
                <img src={posthogLogo} style={{ width: 157, height: 30 }} />
            </div>
            {children}
        </div>
    )
}
