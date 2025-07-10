import { useActions, useValues } from 'kea'
import { useEffect } from 'react'
import useResizeObserver from 'use-resize-observer'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { ToolbarUserIntent } from '~/types'

import { appEditorUrl } from '../AuthorizedUrlList/authorizedUrlListLogic'
import { UserIntentVerb, iframedToolbarBrowserLogic } from './iframedToolbarBrowserLogic'

function IframeErrorOverlay({ userIntent }: { userIntent?: string }): JSX.Element | null {
    const logic = iframedToolbarBrowserLogic()
    const { iframeBanner } = useValues(logic)
    return iframeBanner ? (
        <div className="pointer-events-none absolute flex h-full w-full flex-col items-start px-8 py-4 bg-blend-overlay">
            <LemonBanner className="w-full" type={iframeBanner.level}>
                {iframeBanner.message}. Your site might not allow being embedded in an iframe. You can click "Open in
                toolbar" above to visit your site and {UserIntentVerb[userIntent as ToolbarUserIntent]} there.
            </LemonBanner>
        </div>
    ) : null
}

function LoadingOverlay(): JSX.Element | null {
    const logic = iframedToolbarBrowserLogic()
    const { loading } = useValues(logic)
    return loading ? (
        <div className="pointer-events-none absolute flex h-full w-full flex-col items-center justify-center">
            <Spinner className="text-5xl" textColored={true} />
        </div>
    ) : null
}

export function IframedToolbarBrowser({
    iframeRef,
    userIntent,
}: {
    iframeRef: React.MutableRefObject<HTMLIFrameElement | null>
    userIntent: ToolbarUserIntent
}): JSX.Element | null {
    const logic = iframedToolbarBrowserLogic({ iframeRef, userIntent: userIntent })

    const { browserUrl, initialPath } = useValues(logic)
    const { onIframeLoad, setIframeWidth } = useActions(logic)

    const { width: iframeWidth } = useResizeObserver<HTMLIFrameElement>({ ref: iframeRef })
    useEffect(() => {
        setIframeWidth(iframeWidth ?? null)
    }, [iframeWidth])

    return browserUrl ? (
        <div className="relative h-full w-full flex-1">
            <IframeErrorOverlay userIntent={userIntent} />
            <LoadingOverlay />
            <iframe
                ref={iframeRef}
                className="h-full w-full bg-white"
                src={appEditorUrl(browserUrl + '/' + initialPath, {
                    userIntent: userIntent,
                })}
                onLoad={onIframeLoad}
                // these two sandbox values are necessary so that the site and toolbar can run
                // this is a very loose sandbox,
                // but we specify it so that at least other capabilities are denied
                sandbox="allow-scripts allow-same-origin"
                // we don't allow things such as camera access though
                allow=""
            />
        </div>
    ) : null
}
