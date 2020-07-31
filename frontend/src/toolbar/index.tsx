import '~/toolbar/styles.scss'

import React from 'react'
import ReactDOM from 'react-dom'
import Simmer from 'simmerjs'
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
        <Provider store={getContext().store!}>
            <ToolbarApp {...editorParams} jsURL={editorParams.jsURL || editorParams.apiURL} />
        </Provider>,
        container
    )
}
