import React from 'react'
import { Provider } from 'kea'
import { initKea } from '../frontend/src/initKea'
import '~/styles'

initKea()

export const parameters = {
    actions: { argTypesRegex: '^on[A-Z].*' },
    controls: {
        matchers: {
            color: /(background|color)$/i,
            date: /Date$/,
        },
    },
}

const withKea = (Story, context) => {
    // const theme = getTheme(context.globals.theme)
    return (
        <Provider>
            <Story {...context} />
        </Provider>
    )
}

export const decorators = [withKea]
