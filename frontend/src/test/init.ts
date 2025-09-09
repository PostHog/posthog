import { MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { createMemoryHistory } from 'history'
import { testUtilsPlugin } from 'kea-test-utils'
import posthog from 'posthog-js'

import { dayjs } from 'lib/dayjs'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { organizationLogic } from 'scenes/organizationLogic'
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
    window.POSTHOG_APP_CONTEXT = {
        ...window.POSTHOG_APP_CONTEXT,
        current_team: teamForWindowContext,
        current_project: projectForWindowContext,
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
