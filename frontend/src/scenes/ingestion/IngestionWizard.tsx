import React from 'react'
import './IngestionWizard.scss'

import { VerificationPanel } from 'scenes/ingestion/panels/VerificationPanel'
import { AutocapturePanel } from 'scenes/ingestion/panels/AutocapturePanel'
import { InstructionsPanel } from 'scenes/ingestion/panels/InstructionsPanel'
import { MOBILE, BACKEND, WEB } from 'scenes/ingestion/constants'
import { useValues } from 'kea'
import { ingestionLogic } from 'scenes/ingestion/ingestionLogic'
import { FrameworkPanel } from 'scenes/ingestion/panels/FrameworkPanel'
import { PlatformPanel } from 'scenes/ingestion/panels/PlatformPanel'

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

export default function IngestionWizard(): JSX.Element {
    const { platform, framework, verify } = useValues(ingestionLogic)

    if (verify) {
        return (
            <IngestionContainer>
                <VerificationPanel />
            </IngestionContainer>
        )
    }

    if (framework) {
        return (
            <IngestionContainer>
                <InstructionsPanel />
            </IngestionContainer>
        )
    }

    if (!platform) {
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
