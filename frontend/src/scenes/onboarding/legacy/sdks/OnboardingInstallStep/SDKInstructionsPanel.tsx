import { IconArrowLeft } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { type SDK, SDKInstructionsMap } from '~/types'

import { type AdblockDetectionResult } from '../hooks/useAdblockDetection'
import { useInstallationComplete } from '../hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from '../RealtimeCheckIndicator'
import { SDKSnippet } from '../SDKSnippet'
import { NextButton } from './NextButton'

const INSTALL_DOCS_URL = 'https://posthog.com/docs/getting-started/install'

export interface SDKInstructionsPanelProps {
    sdk?: SDK
    sdkInstructionMap: SDKInstructionsMap
    adblockResult: AdblockDetectionResult
    /** Returns to whatever the caller shows behind the instructions, usually the SDK grid. */
    onBack: () => void
    verifyingProperty?: string
    verifyingName?: string
    hideInstallationCheck?: boolean
    /** Overrides the legacy onboardingLogic advance the footer's NextButton dispatches by default. */
    onAdvance?: () => void
}

/** Install steps for one SDK, plus the live verification footer. Sized by its container. */
export function SDKInstructionsPanel({
    sdk,
    sdkInstructionMap,
    adblockResult,
    onBack,
    verifyingProperty = 'ingested_event',
    verifyingName = 'event',
    hideInstallationCheck = false,
    onAdvance,
}: SDKInstructionsPanelProps): JSX.Element {
    const installationCompleteFromTeam = useInstallationComplete(verifyingProperty)
    const installationComplete = hideInstallationCheck || installationCompleteFromTeam

    const sdkInstructions = sdkInstructionMap[sdk?.key as keyof typeof sdkInstructionMap] as
        | (() => JSX.Element)
        | undefined

    return (
        <div className="flex flex-col h-full">
            <header className="p-4 flex items-center gap-2">
                <LemonButton icon={<IconArrowLeft />} onClick={onBack} size="xsmall">
                    All SDKs
                </LemonButton>
            </header>
            <div className="flex-grow overflow-y-auto px-4 py-2">
                {sdk?.key && sdkInstructions ? (
                    <SDKSnippet sdk={sdk} sdkInstructions={sdkInstructions} />
                ) : (
                    <div className="flex flex-col items-start gap-3 py-4">
                        <h3 className="text-xl font-bold m-0">
                            {sdk?.name ? `Install ${sdk.name}` : 'Install PostHog'}
                        </h3>
                        <p className="text-sm text-muted m-0">
                            We don't have setup steps in the app for this SDK yet. The install docs cover it.
                        </p>
                        <LemonButton type="primary" to={sdk?.docsLink ?? INSTALL_DOCS_URL} targetBlank>
                            Read the install docs
                        </LemonButton>
                    </div>
                )}
            </div>
            {!hideInstallationCheck && !installationComplete && (
                <div className="px-4 py-2">
                    <AdblockWarning adblockResult={adblockResult} />
                </div>
            )}
            <footer className="sticky bottom-0 w-full bg-bg-light dark:bg-bg-depth rounded-b-sm p-2 flex justify-between items-center gap-2 px-4">
                {!hideInstallationCheck ? (
                    <RealtimeCheckIndicator teamPropertyToVerify={verifyingProperty} listeningForName={verifyingName} />
                ) : (
                    <span />
                )}
                <NextButton installationComplete={installationComplete} onAdvance={onAdvance} />
            </footer>
        </div>
    )
}
