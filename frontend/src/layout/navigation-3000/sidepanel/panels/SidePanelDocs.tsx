import { useActions, useValues } from 'kea'
import { POSTHOG_WEBSITE_ORIGIN, sidePanelDocsLogic } from './sidePanelDocsLogic'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { SidePanelPaneHeader } from '../components/SidePanelPane'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'
import { IconExternal } from '@posthog/icons'
import { themeLogic } from '../../themeLogic'

function SidePanelDocsSkeleton(): JSX.Element {
    return (
        <div className="absolute inset-0 p-4 space-y-2">
            <LemonSkeleton className="w-full h-10 mb-12" />
            <LemonSkeleton className="w-1/3 h-8" />
            <LemonSkeleton className="w-1/2 h-4 mb-10" />
            <LemonSkeleton className="w-full h-4" />
            <LemonSkeleton className="w-full h-4 opacity-80" />
            <LemonSkeleton className="w-full h-4 opacity-60" />
            <LemonSkeleton className="w-full h-4 opacity-40" />
            <LemonSkeleton className="w-1/2 h-4 opacity-20" />
        </div>
    )
}

export const SidePanelDocs = (): JSX.Element => {
    const { iframeSrc, currentUrl } = useValues(sidePanelDocsLogic)
    const { updatePath, unmountIframe, closeSidePanel } = useActions(sidePanelDocsLogic)
    const ref = useRef<HTMLIFrameElement>(null)
    const [ready, setReady] = useState(false)
    const { isDarkModeOn } = useValues(themeLogic)

    useEffect(() => {
        ref.current?.contentWindow?.postMessage(
            {
                type: 'theme-toggle',
                isDarkModeOn,
            },
            '*'
        )
    }, [isDarkModeOn, ref.current])

    useEffect(() => {
        const onMessage = (event: MessageEvent): void => {
            if (event.origin === POSTHOG_WEBSITE_ORIGIN) {
                if (event.data.type === 'internal-navigation' && event.data.url) {
                    updatePath(event.data.url)
                }
                if (event.data.type === 'docs-ready') {
                    setReady(true)
                }
            }
        }

        window.addEventListener('message', onMessage)

        return () => window.removeEventListener('message', onMessage)
    }, [ref.current])

    useEffect(() => {
        return unmountIframe
    }, [])

    return (
        <>
            <SidePanelPaneHeader>
                <LemonButton
                    size="small"
                    sideIcon={<IconExternal />}
                    to={currentUrl}
                    targetBlank
                    onClick={() => closeSidePanel()}
                >
                    Open on posthog.com
                </LemonButton>
            </SidePanelPaneHeader>
            <div className="relative flex-1">
                <iframe src={iframeSrc} title="Docs" className={clsx('w-full h-full', !ready && 'hidden')} ref={ref} />

                {!ready && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
