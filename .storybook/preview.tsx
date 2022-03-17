import * as React from 'react'
import '~/styles'
import { worker } from '~/mocks/browser'
import { loadPostHogJS } from '~/loadPostHogJS'
import { KeaStory } from './kea-story'
import { storybookAppContext } from 'storybook/app-context'

const setupMsw = () => {
    // Make sure the msw worker is started
    worker.start()
    ;(window as any).__mockServiceWorker = worker
    ;(window as any).POSTHOG_APP_CONTEXT = storybookAppContext
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

// Setup storybook global parameters. See https://storybook.js.org/docs/react/writing-stories/parameters#global-parameters
export const parameters = {
    actions: { argTypesRegex: '^on[A-Z].*', disabled: true },
    controls: {
        matchers: {
            color: /(background|color)$/i,
            date: /Date$/,
        },
    },
    options: {
        // automatically show code panel
        showPanel: true,
        storySort: (a: any, b: any) => {
            return a[1].kind === b[1].kind ? 0 : a[1].title.localeCompare(b[1].title, undefined, { numeric: true })
        },
    },
    viewMode: 'docs',
    // auto-expand code blocks in docs
    docs: {
        source: { state: 'open' },
    },
}

// Setup storybook global decorators. See https://storybook.js.org/docs/react/writing-stories/decorators#global-decorators
export const decorators = [
    // Make sure the msw service worker is started, and reset the handlers to
    // defaults.
    (Story: any) => {
        return (
            <KeaStory>
                <Story />
            </KeaStory>
        )
    },
]
