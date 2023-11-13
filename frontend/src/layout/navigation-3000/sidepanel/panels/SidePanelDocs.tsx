import { useActions, useValues } from 'kea'
import { POSTHOG_WEBSITE_ORIGIN, sidePanelDocsLogic } from './sidePanelDocsLogic'
import { useEffect, useRef } from 'react'
import clsx from 'clsx'

export const SidePanelDocs = (): JSX.Element => {
    const { iframeSrc } = useValues(sidePanelDocsLogic)
    const { updatePath, unmountIframe } = useActions(sidePanelDocsLogic)
    const ref = useRef<HTMLIFrameElement>(null)

    useEffect(() => {
        const onMessage = (event: MessageEvent): void => {
            if (event.origin === POSTHOG_WEBSITE_ORIGIN) {
                if (typeof event.data === 'string') {
                    updatePath(event.data)
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
        <div className="w-full h-full overflow-hidden">
            <iframe src={iframeSrc} title="Docs" className={clsx('w-full h-full')} ref={ref} />
        </div>
    )
}
