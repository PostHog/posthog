import { useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { App } from 'scenes/App'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SettingSectionId } from '../types'

const READY_MARKER = 'settings-story-ready'

export const SETTINGS_STORY_TEST_OPTIONS = { waitForSelector: `[data-attr="${READY_MARKER}"]` }

/** Renders nothing until the organization and team have loaded. The nav and section list depend on both, so an earlier mount can snapshot a short nav or "Setting not found". */
function SettingsStoryReady({ children }: { children: React.ReactNode }): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)

    if (!currentOrganization || !currentTeam) {
        return null
    }

    return (
        <>
            <div data-attr={READY_MARKER} className="absolute size-px opacity-0 pointer-events-none" />
            {children}
        </>
    )
}

function SettingsSectionApp({ sectionId }: { sectionId: SettingSectionId }): JSX.Element {
    const pushedSectionId = useRef<SettingSectionId | null>(null)

    if (pushedSectionId.current !== sectionId) {
        pushedSectionId.current = sectionId
        // A useEffect push runs after the first paint, so the snapshot could capture the homepage frame.
        router.actions.push(urls.settings(sectionId))
    }

    return <App />
}

export function SettingsStoryApp({ sectionId }: { sectionId: SettingSectionId }): JSX.Element {
    return (
        <SettingsStoryReady>
            <SettingsSectionApp sectionId={sectionId} />
        </SettingsStoryReady>
    )
}
