import { useValues } from 'kea'
import { router } from 'kea-router'
import { useRef } from 'react'

import { App } from 'scenes/App'
import { organizationLogic } from 'scenes/organizationLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SettingSectionId } from '../types'

export const SETTINGS_STORY_TEST_OPTIONS = { waitForSelector: '[data-attr^="settings-menu-item-"]' }

/** The nav and section list depend on the organization and team, so a story that mounts earlier can snapshot a short nav or "Setting not found". */
export function SettingsStoryApp({ sectionId }: { sectionId: SettingSectionId }): JSX.Element | null {
    const { currentOrganization } = useValues(organizationLogic)
    const { currentTeam } = useValues(teamLogic)
    const pushed = useRef(false)

    if (!currentOrganization || !currentTeam) {
        return null
    }

    if (!pushed.current) {
        pushed.current = true
        // A useEffect push runs after the first paint, so the snapshot could capture the homepage frame.
        router.actions.push(urls.settings(sectionId))
    }

    return <App />
}
