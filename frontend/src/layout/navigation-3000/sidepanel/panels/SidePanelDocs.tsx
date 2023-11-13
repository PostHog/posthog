import { useActions, useValues } from 'kea'
import { POSTHOG_WEBSITE_ORIGIN, sidePanelDocsLogic } from './sidePanelDocsLogic'
import { useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import { SidePanelPaneHeader } from '../components/SidePanelPane'
import { LemonButton } from '@posthog/lemon-ui'
import { IconExternal } from '@posthog/icons'

export const SidePanelDocs = (): JSX.Element => {
    const { iframeSrc, currentUrl } = useValues(sidePanelDocsLogic)
    const { updatePath, unmountIframe, closeSidePanel } = useActions(sidePanelDocsLogic)
    const ref = useRef<HTMLIFrameElement>(null)
    const [ready, setReady] = useState(false)

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
            <iframe
                src={iframeSrc}
                title="Docs"
                className={clsx('flex-1 w-full h-full', !ready && 'hidden')}
                ref={ref}
            />
        </>
    )
}
