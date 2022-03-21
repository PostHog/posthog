import 'react-toastify/dist/ReactToastify.css'
import '~/styles'
import './styles.scss'

import React from 'react'
import ReactDOM from 'react-dom'
import Simmer from '@posthog/simmerjs'
import { getContext } from 'kea'
import { Provider } from 'react-redux'
import { initKea } from '~/initKea'
import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { EditorProps } from '~/types'
import { PostHog } from 'posthog-js'
;(window as any)['simmer'] = new Simmer(window, { depth: 8 })
;(window as any)['ph_load_editor'] = function (editorParams: EditorProps, posthog: PostHog) {
    initKea()
    const container = document.createElement('div')
    document.body.appendChild(container)

    if (!posthog) {
        console.warn(
            '⚠️⚠️⚠️ Loaded toolbar via old version of posthog-js that does not support feature flags. Please upgrade! ⚠️⚠️⚠️'
        )
    }

    ReactDOM.render(
        <Provider store={getContext().store}>
            <ToolbarApp
                {...editorParams}
                actionId={parseInt(String(editorParams.actionId))}
                jsURL={editorParams.jsURL || editorParams.apiURL}
                posthog={posthog}
            />
        </Provider>,
        container
    )
}

// Expose `window.getToolbarReduxState()` to make snapshots to storybook easy
if (typeof window !== 'undefined') {
    // Disabled in production to prevent leaking secret data, personal API keys, etc
    if (process.env.NODE_ENV === 'development') {
        ;(window as any).getToolbarReduxState = () => getContext().store.getState()
    }
}
