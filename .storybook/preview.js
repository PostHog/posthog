import React from 'react'
import { getContext } from 'kea'
import { loadPostHogJS } from '~/loadPostHogJS'
import '~/styles'

loadPostHogJS()
window.getReduxState = () => getContext().store.getState()

export const parameters = {
    actions: { argTypesRegex: '^on[A-Z].*' },
    controls: {
        matchers: {
            color: /(background|color)$/i,
            date: /Date$/,
        },
    },

    options: {
        // opt in to panels in your story by overridding `export const parameters`
        showPanel: false,
    },
}

if (typeof global.process === 'undefined') {
    const { worker } = require('../frontend/src/mocks/browser')
    worker.start()
}
