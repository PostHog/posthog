import '~/styles'
import './styles.scss'

import ReactDOM from 'react-dom'
import { initKea } from '~/initKea'
import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { ToolbarParams } from '~/types'
import { PostHog } from 'posthog-js'
;(window as any)['ph_load_toolbar'] = function (toolbarParams: ToolbarParams, posthog: PostHog) {
    initKea()
    const container = document.createElement('div')
    document.body.appendChild(container)

    if (!posthog) {
        console.warn(
            '⚠️⚠️⚠️ Loaded toolbar via old version of posthog-js that does not support feature flags. Please upgrade! ⚠️⚠️⚠️'
        )
    }

    ReactDOM.render(
        <ToolbarApp
            {...toolbarParams}
            actionId={parseInt(String(toolbarParams.actionId))}
            jsURL={toolbarParams.jsURL || toolbarParams.apiURL}
            posthog={posthog}
        />,
        container
    )
}
/** @deprecated, use "ph_load_toolbar" instead */
;(window as any)['ph_load_editor'] = (window as any)['ph_load_toolbar']
