import '~/styles'
import './storybook.scss'
import type { Meta } from '@storybook/react'
import { worker } from '~/mocks/browser'
import { loadPostHogJS } from '~/loadPostHogJS'
import { getStorybookAppContext } from './app-context'
import { withKea } from './decorators/withKea'
import { withMockDate } from './decorators/withMockDate'
import { defaultMocks } from '~/mocks/handlers'
import { withSnapshotsDisabled } from './decorators/withSnapshotsDisabled'

const setupMsw = () => {
    // Make sure the msw worker is started
    worker.start({
        quiet: true,
    })
    ;(window as any).__mockServiceWorker = worker
    ;(window as any).POSTHOG_APP_CONTEXT = getStorybookAppContext()
}
setupMsw()

const setupPosthogJs = () => {
    // Make sure we don't hit production posthog. We want to control requests to,
    // e.g. `/decide/` for feature flags
    window.JS_POSTHOG_HOST = window.location.origin

    loadPostHogJS()
}
setupPosthogJs()

/** Storybook global parameters. See https://storybook.js.org/docs/react/writing-stories/parameters#global-parameters */
export const parameters = {
    chromatic: { disableSnapshot: true }, // TODO: Make snapshots the default, instead disable them on a per-story basis
    actions: { argTypesRegex: '^on[A-Z].*', disabled: true },
    controls: {
        matchers: {
            color: /(background|color)$/i,
            date: /Date$/,
        },
    },
    options: {
        // automatically show code panel
        showPanel: false,
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
        source: { state: 'closed' },
    },
    msw: {
        mocks: defaultMocks,
    },
}

// Setup storybook global decorators. See https://storybook.js.org/docs/react/writing-stories/decorators#global-decorators
export const decorators: Meta['decorators'] = [
    withSnapshotsDisabled,
    // Make sure the msw service worker is started, and reset the handlers to defaults.
    withKea,
    // Allow us to time travel to ensure our stories don't change over time.
    // To mock a date for a story, set the `mockDate` parameter.
    withMockDate,
]
