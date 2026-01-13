import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { SidePanelDocsSkeleton } from './SidePanelDocs'
import { sidePanelChangelogLogic } from './sidePanelChangelogLogic'

export function SidePanelChangelog(): JSX.Element {
    const { changelogUrl, iframeReady } = useValues(sidePanelChangelogLogic)
    const { closeSidePanel, setIframeReady } = useActions(sidePanelChangelogLogic)

    return (
        <>
            <SidePanelPaneHeader>
                <div className="flex-1" />
                <LemonButton
                    size="small"
                    targetBlank
                    onClick={() => {
                        window.open(changelogUrl, '_blank')?.focus()
                        closeSidePanel()
                    }}
                >
                    Open in new tab
                </LemonButton>
            </SidePanelPaneHeader>
            <div className="relative flex-1 overflow-hidden">
                <iframe
                    src={changelogUrl}
                    title="Changelog"
                    className={clsx('w-full h-full', !iframeReady && 'hidden')}
                    onLoad={() => setIframeReady(true)}
                />
                {!iframeReady && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
