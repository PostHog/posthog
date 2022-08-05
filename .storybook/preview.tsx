import * as React from 'react'
import '~/styles'
import './storybook.scss'
import { worker } from '~/mocks/browser'
import { loadPostHogJS } from '~/loadPostHogJS'
import { KeaStory } from './kea-story'
import { getStorybookAppContext } from 'storybook/app-context'
import { useAvailableFeatures } from '~/mocks/features'

const setupMsw = () => {
    // Make sure the msw worker is started
    worker.start()
    ;(window as any).__mockServiceWorker = worker
    ;(window as any).POSTHOG_APP_CONTEXT = getStorybookAppContext()
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
        storySort: {
            method: 'alphabetical',
            order: [
                'Lemon UI',
                ['Overview', 'Utilities', 'Icons'],
                'Components',
                'Forms',
                ['Field'],
                'Filters',
                'Layout',
            ],
            includeName: true,
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
        // Reset enabled enterprise features. Overwrite this line within your stories.
        useAvailableFeatures([])
        return (
            <KeaStory>
                <Story />
            </KeaStory>
        )
    },
]
