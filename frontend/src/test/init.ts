import { initKea } from '~/initKea'
import { testUtilsPlugin } from 'kea-test-utils'
import { createMemoryHistory } from 'history'
import posthog from 'posthog-js'
import { AppContext } from '~/types'
import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'
import { dayjs } from 'lib/dayjs'

export function initKeaTests(): void {
    dayjs.tz.setDefault('UTC')
    window.POSTHOG_APP_CONTEXT = {
        current_team: MOCK_DEFAULT_TEAM,
        ...window.POSTHOG_APP_CONTEXT,
    } as unknown as AppContext
    posthog.init('no token', {
        api_host: 'borked',
        test: true,
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
}
