import { useActions } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { useEffect, useRef, useState } from 'react'

// The PostHog website origin
const POSTHOG_WEBSITE_ORIGIN = 'https://posthog.com'

export function InKeepMaxChatInterface(): JSX.Element {
    const [isLoading, setIsLoading] = useState(true)
    const iframeRef = useRef<HTMLIFrameElement>(null)
    const { closeInKeepMaxChatInterface } = useActions(supportLogic)

    // Check if the InKeep feature flag is enabled
    const isInKeepMaxEnabled = useFeatureFlag('INKEEP_MAX_SUPPORT_SIDEBAR')

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
                            allow="clipboard-write"
                            title="Max AI Chat"
                            loading="eager"
                            onLoad={() => setIsLoading(false)}
                            onError={() => setIsLoading(false)}
                        />
                    </div>
                </div>
            </div>
        </div>
    )
}
