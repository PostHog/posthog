import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { createMemoryHistory } from 'history'
import { testUtilsPlugin } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKea } from '~/initKea'
import { AppContext, ProjectType, TeamType } from '~/types'

process.on('unhandledRejection', (err) => {
    console.warn(err)
})

export function initKeaTests(
    mountCommonLogic = true,
    teamForWindowContext: TeamType = MOCK_DEFAULT_TEAM,
    projectForWindowContext: ProjectType = MOCK_DEFAULT_PROJECT
): void {
    dayjs.tz.setDefault('UTC')
    const existingAppContext = window.POSTHOG_APP_CONTEXT
    window.POSTHOG_APP_CONTEXT = {
        ...existingAppContext,
        current_team: teamForWindowContext,
        current_project: projectForWindowContext,
        // Bootstrap organization synchronously (mirrors production where it's always in the page context).
        // Preserve any current_user the test may have set before calling initKeaTests.
        // Use `in` check so explicitly-set `null` (e.g. toolbar shim tests) is preserved as-is.
        current_user:
            existingAppContext && 'current_user' in existingAppContext
                ? existingAppContext.current_user
                : { organization: MOCK_DEFAULT_ORGANIZATION },
        // Default to $pageview in tests (simulating a team that has pageview events)
        default_event_name: '$pageview',
    } as unknown as AppContext
    posthog.init('no token', {
        autocapture: false,
        disable_session_recording: true,
        advanced_disable_decide: true,
        opt_out_capturing_by_default: true,
        loaded: (p) => {
            p.opt_out_capturing()
        },
    })

    const history = createMemoryHistory()
    ;(history as any).pushState = history.push
    ;(history as any).replaceState = history.replace
    initKea({ beforePlugins: [testUtilsPlugin], routerLocation: history.location, routerHistory: history })
    if (mountCommonLogic) {
        preflightLogic.mount()
        teamLogic.mount()
        projectLogic.mount()
        organizationLogic.mount()
    }
}
