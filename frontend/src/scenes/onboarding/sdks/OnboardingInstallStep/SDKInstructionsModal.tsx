import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonModal, SpinnerOverlay } from '@posthog/lemon-ui'

import { type SDK, SDKInstructionsMap } from '~/types'

import { type AdblockDetectionResult } from '../hooks/useAdblockDetection'
import { useInstallationComplete } from '../hooks/useInstallationComplete'
import { AdblockWarning, RealtimeCheckIndicator } from '../RealtimeCheckIndicator'
import { SDKSnippet } from '../SDKSnippet'
import { NextButton } from './NextButton'

interface SDKInstructionsModalProps {
    isOpen: boolean
    onClose: () => void
    sdk?: SDK
    sdkInstructionMap: SDKInstructionsMap
    adblockResult: AdblockDetectionResult
    verifyingProperty?: string
    verifyingName?: string
}

export function SDKInstructionsModal({
    isOpen,
    onClose,
    sdk,
    sdkInstructionMap,
    adblockResult,
    verifyingProperty = 'ingested_event',
    verifyingName = 'event',
}: SDKInstructionsModalProps): JSX.Element {
    const installationComplete = useInstallationComplete(verifyingProperty)

    const sdkInstructions = sdkInstructionMap[sdk?.key as keyof typeof sdkInstructionMap] as
        | (() => JSX.Element)
        | undefined

    return (
        <LemonModal isOpen={isOpen} onClose={onClose} simple title="">
            {!sdk?.key || !sdkInstructions ? (
                <SpinnerOverlay />
            ) : (
                <div className="flex flex-col h-full">
                    <header className="p-4 flex items-center gap-2">
                        <LemonButton icon={<IconArrowLeft />} onClick={onClose} size="xsmall">
                            All SDKs
                        </LemonButton>
                    </header>
                    <div className="flex-grow overflow-y-auto px-4 py-2">
                        <SDKSnippet sdk={sdk} sdkInstructions={sdkInstructions} />
                    </div>
                    {!installationComplete && (
                        <div className="px-4 py-2">
                            <AdblockWarning adblockResult={adblockResult} />
                        </div>
                    )}
                    <footer className="sticky bottom-0 w-full bg-bg-light dark:bg-bg-depth rounded-b-sm p-2 flex justify-between items-center gap-2 px-4">
                        <RealtimeCheckIndicator
                            teamPropertyToVerify={verifyingProperty}
                            listeningForName={verifyingName}
                        />
                        <NextButton installationComplete={installationComplete} />
                    </footer>
                </div>
            )}
        </LemonModal>
    )
}
