import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { createMemoryHistory } from 'history'
import { testUtilsPlugin } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { initKea } from '~/initKea'
import { AppContext, OrganizationType, ProjectType, TeamType, UserType } from '~/types'

process.on('unhandledRejection', (err) => {
    console.warn(err)
})

export function initKeaTests(
    mountCommonLogic = true,
    teamForWindowContext: TeamType = MOCK_DEFAULT_TEAM,
    projectForWindowContext: ProjectType = MOCK_DEFAULT_PROJECT,
    organizationForWindowContext: OrganizationType = MOCK_DEFAULT_ORGANIZATION,
    userForWindowContext: UserType = MOCK_DEFAULT_USER
): void {
    dayjs.tz.setDefault('UTC')
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        current_team: teamForWindowContext,
        current_project: projectForWindowContext,
        current_user: {
            ...userForWindowContext,
            organization: organizationForWindowContext,
            team: teamForWindowContext,
        },
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
