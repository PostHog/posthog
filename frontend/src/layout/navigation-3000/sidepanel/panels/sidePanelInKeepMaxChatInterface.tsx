import { offset } from '@floating-ui/react'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useEffect, useRef, useState } from 'react'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

// The PostHog website origin
const POSTHOG_WEBSITE_ORIGIN = 'https://posthog.com'

export function InKeepMaxChatInterface(): JSX.Element {
    const { dataProcessingAccepted } = useValues(maxGlobalLogic)
    const { acceptDataProcessing } = useActions(maxGlobalLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const [isLoading, setIsLoading] = useState(true)
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const { closeInKeepMaxChatInterface } = useActions(supportLogic)

    // Check if the InKeep feature flag is enabled
    const isInKeepMaxEnabled = featureFlags[FEATURE_FLAGS.INKEEP_MAX_SUPPORT_SIDEBAR]

    useEffect(() => {
        if (!iframeRef.current) {
            return
        }

        // Store a reference to the current iframe element
        const iframe = iframeRef.current

        const handleIframeLoad = (): void => {
            setIsLoading(false)
        }

        iframe.addEventListener('load', handleIframeLoad)

        return () => {
            // Use the stored reference in the cleanup function
            iframe.removeEventListener('load', handleIframeLoad)
        }
    }, [])

    if (!isInKeepMaxEnabled) {
        return <></>
    }

    return (
        <div className="relative h-full flex flex-col">
            {dataProcessingAccepted ? (
                <div className="relative flex-1 overflow-hidden h-full flex flex-col">
                    <div className="relative w-full h-full">
                        {isLoading && (
                            <div className="flex items-center justify-center h-full absolute top-0 left-0 w-full z-10 bg-bg-light dark:bg-bg-dark bg-opacity-80 dark:bg-opacity-80">
                                <div className="flex items-center gap-2">
                                    <span>Loading Max AI...</span>
                                    <Spinner className="text-lg" />
                                </div>
                            </div>
                        )}
                        {/* Close button positioned at the bottom left */}
                        <div className="absolute bottom-4 left-4 z-20">
                            <button
                                type="button"
                                onClick={() => closeInKeepMaxChatInterface()}
                                className="px-3 py-1 bg-bg-light dark:bg-dark hover:bg-bg-light/80 dark:hover:bg-dark/80 rounded text-sm shadow-md"
                            >
                                Close
                            </button>
                        </div>
                        {/* Simple iframe with no background styling */}
                        <div className="w-full h-full overflow-hidden bg-bg-light dark:bg-dark">
                            <iframe
                                ref={iframeRef}
                                src={`${POSTHOG_WEBSITE_ORIGIN}/docs/new-to-posthog/understand-posthog?chat=open`}
                                className="w-full h-full min-h-[500px] border-0"
                                allow="clipboard-write; microphone"
                                title="Max AI Chat"
                                loading="eager"
                                onLoad={() => setIsLoading(false)}
                                onError={() => setIsLoading(false)}
                            />
                        </div>
                    </div>
                </div>
            ) : (
                <AIConsentPopoverWrapper placement="right-start" middleware={[offset(-12)]} showArrow>
                    <div className="p-4">
                        <h3>Accept AI data processing to chat with Max</h3>
                        <p className="mt-2">
                            Max is powered by AI models that require data processing consent before you can chat.
                        </p>
                        <button
                            type="button"
                            className="mt-4 w-full bg-primary text-white py-2 px-4 rounded"
                            onClick={() => acceptDataProcessing()}
                        >
                            Accept and continue
                        </button>
                    </div>
                </AIConsentPopoverWrapper>
            )}
        </div>
    )
}
