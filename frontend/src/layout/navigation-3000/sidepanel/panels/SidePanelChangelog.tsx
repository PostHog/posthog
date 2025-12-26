import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { sceneLogic } from 'scenes/sceneLogic'

import { SidePanelPaneHeader } from '../components/SidePanelPaneHeader'
import { sidePanelStateLogic } from '../sidePanelStateLogic'
import { SidePanelDocsSkeleton } from './SidePanelDocs'

const CHANGELOG_BASE_URL = 'https://posthog.com/changelog'

export function SidePanelChangelog(): JSX.Element {
    const { closeSidePanel } = useActions(sidePanelStateLogic)
    const { sceneConfig } = useValues(sceneLogic)
    const [ready, setReady] = useState(false)

    const teamSlug = sceneConfig?.changelogTeamSlug
    const changelogUrl = teamSlug ? `${CHANGELOG_BASE_URL}?team=${encodeURIComponent(teamSlug)}` : CHANGELOG_BASE_URL

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
                    className={clsx('w-full h-full', !ready && 'hidden')}
                    onLoad={() => setReady(true)}
                />
                {!ready && <SidePanelDocsSkeleton />}
            </div>
        </>
    )
}
