import React from 'react'
import './IngestionWizard.scss'

import { VerificationPanel } from 'scenes/ingestion/panels/VerificationPanel'
import { AutocapturePanel } from 'scenes/ingestion/panels/AutocapturePanel'
import { InstructionsPanel } from 'scenes/ingestion/panels/InstructionsPanel'
import { MOBILE, BACKEND, WEB } from 'scenes/ingestion/constants'
import { useValues, useActions } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { FrameworkPanel } from 'scenes/ingestion/panels/FrameworkPanel'
import { FrameworkGrid } from 'scenes/ingestion/panels/FrameworkGrid'
import { PlatformPanel } from 'scenes/ingestion/panels/PlatformPanel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { SceneExport } from 'scenes/sceneTypes'

export const scene: SceneExport = {
    component: IngestionWizard,
    logic: ingestionLogic,
}

export function IngestionContainer({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        <div
            className="background"
            style={{
                display: 'flex',
                height: 'calc(100vh - 50px)',
                width: '100vw',
                alignItems: 'center',
                justifyContent: 'center',
            }}
        >
            {children}
        </div>
    )
}

export function IngestionWizard(): JSX.Element {
    const { platform, framework, verify } = useValues(ingestionLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { reportIngestionLandingSeen } = useActions(eventUsageLogic)

    if (verify) {
        return (
            <IngestionContainer>
                <VerificationPanel />
            </IngestionContainer>
        )
    }

    if (featureFlags[FEATURE_FLAGS.INGESTION_GRID] && !framework) {
        reportIngestionLandingSeen(true)
        return (
            <IngestionContainer>
                <FrameworkGrid />
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

    return <></>
}

export default IngestionWizard
