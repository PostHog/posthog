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
}

export const decorators = []
