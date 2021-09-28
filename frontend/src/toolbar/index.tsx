import 'react-toastify/dist/ReactToastify.css'
import '~/styles'
import '~/toolbar/styles.scss'

import React from 'react'
import ReactDOM from 'react-dom'
import Simmer from '@posthog/simmerjs'
import { getContext } from 'kea'
import { Provider } from 'react-redux'
import { initKea } from '~/initKea'
import { ToolbarApp } from '~/toolbar/ToolbarApp'
import { EditorProps } from '~/types'

initKea()
;(window as any)['simmer'] = new Simmer(window, { depth: 8 })
;(window as any)['ph_load_editor'] = function (editorParams: EditorProps) {
    const container = document.createElement('div')
    document.body.appendChild(container)

    ReactDOM.render(
        <Provider store={getContext().store}>
            <ToolbarApp
                {...editorParams}
                actionId={
                    typeof editorParams.actionId === 'string' ? parseInt(editorParams.actionId) : editorParams.actionId
                }
                jsURL={editorParams.jsURL || editorParams.apiURL}
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
