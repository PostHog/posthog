import React from 'react'
import { getContext } from 'kea'
import '~/styles'
import { worker } from '../frontend/src/mocks/browser'
import { loadPostHogJS } from '~/loadPostHogJS'
import { withApi } from './ApiSelector/withApi'

const setupMsw = () => {
    // Make sure the msw worker is started, if we're running in browser
    // NOTE: we could be running in node for instance
    if (typeof window.process === 'undefined') {
        worker.start()
    }
}

setupMsw()

const setupPosthogJs = () => {
    // Make sure we don't hit production posthog. We want to control requests to,
    // e.g. `/decide/` for feature flags
    window.JS_POSTHOG_HOST = window.location.origin

    // We don't be doing any authn so we can just use a fake key
    window.JS_POSTHOG_API_KEY = 'dummy-key'

    loadPostHogJS()
}

setupPosthogJs()

window.getReduxState = () => getContext().store.getState()

// Setup storybook global parameters. See https://storybook.js.org/docs/react/writing-stories/parameters#global-parameters
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

// Setup storybook global decorators. See https://storybook.js.org/docs/react/writing-stories/decorators#global-decorators
export const decorators = [
    // Make sure the msw service worker is started, and reset the handlers to
    // defaults.
    (Story) => {
        worker.resetHandlers()
        return <Story />
    },
    withApi,
]
