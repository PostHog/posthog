import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { createMemoryHistory } from 'history'
import { testUtilsPlugin } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKea } from '~/initKea'
import { AppContext, OrganizationType, ProjectType, TeamType } from '~/types'

process.on('unhandledRejection', (err) => {
    console.warn(err)
})

export function initKeaTests(
    mountCommonLogic = true,
    teamForWindowContext: TeamType = MOCK_DEFAULT_TEAM,
    projectForWindowContext: ProjectType = MOCK_DEFAULT_PROJECT,
    organizationForWindowContext?: OrganizationType
): void {
    dayjs.tz.setDefault('UTC')
    const existingAppContext = window.POSTHOG_APP_CONTEXT
    const orgToUse = organizationForWindowContext ?? MOCK_DEFAULT_ORGANIZATION
    window.POSTHOG_APP_CONTEXT = {
        ...existingAppContext,
        current_team: teamForWindowContext,
        current_project: projectForWindowContext,
        // Bootstrap user and organization synchronously (mirrors production where they're always
        // in the server-rendered page context).
        // When an explicit organization is passed, always build a fresh current_user with it.
        // Otherwise, preserve any current_user the test may have set before calling initKeaTests
        // (e.g. toolbar shim tests set current_user: null, userLogic tests set a custom user).
        current_user:
            organizationForWindowContext !== undefined
                ? { ...MOCK_DEFAULT_USER, organization: organizationForWindowContext }
                : existingAppContext && 'current_user' in existingAppContext
                  ? existingAppContext.current_user
                  : { ...MOCK_DEFAULT_USER, organization: orgToUse },
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
