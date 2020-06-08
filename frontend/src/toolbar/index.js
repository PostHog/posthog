import '~/toolbar/styles.scss'

import React from 'react'
import ReactDOM from 'react-dom'
import Simmer from 'simmerjs'
import { getContext } from 'kea'
import { Provider } from 'react-redux'
import { initKea } from '~/initKea'
import { ToolbarApp } from '~/toolbar/ToolbarApp'

initKea()

window.simmer = new Simmer(window, { depth: 8 })

window.ph_load_editor = function(editorParams) {
    let container = document.createElement('div')
    document.body.appendChild(container)

    ReactDOM.render(
        <Provider store={getContext().store}>
            <ToolbarApp
                jsURL={editorParams.jsURL || editorParams.apiURL}
                apiURL={editorParams.apiURL}
                temporaryToken={editorParams.temporaryToken}
                actionId={editorParams.actionId}
                startMinimized={editorParams.minimized}
            />
        </Provider>,
        container
    )
}
