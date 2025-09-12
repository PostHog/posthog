import '~/styles'

import { Controls, Description, Primary, Stories, Subtitle, Title } from '@storybook/blocks'
import type { Meta, Parameters, Preview } from '@storybook/react'

import { apiHostOrigin } from 'lib/utils/apiHost'

import { loadPostHogJS } from '~/loadPostHogJS'
import { worker } from '~/mocks/browser'
import { defaultMocks } from '~/mocks/handlers'

import { getStorybookAppContext } from './app-context'
import { withFeatureFlags } from './decorators/withFeatureFlags'
import { withKea } from './decorators/withKea'
import { withMockDate } from './decorators/withMockDate'
import { withPageUrl } from './decorators/withPageUrl'
import { withTheme } from './decorators/withTheme'

const setupMsw = (): void => {
    // Make sure the msw worker is started
    worker.start({
        quiet: true,
        onUnhandledRequest(request, print) {
            // MSW warns on all unhandled requests, but we don't necessarily care
            const pathAllowList = ['/images/']

            if (pathAllowList.some((path) => request.url.pathname.startsWith(path))) {
                return
            }

            // Otherwise, default MSW warning behavior
            print.warning()
        },
    })
    ;(window as any).__mockServiceWorker = worker
    ;(window as any).POSTHOG_APP_CONTEXT = getStorybookAppContext()
}
setupMsw()

const setupPosthogJs = (): void => {
    // Make sure we don't hit production posthog. We want to control requests to,
    // e.g. `/decide/` for feature flags
    window.JS_POSTHOG_HOST = apiHostOrigin()

    loadPostHogJS()
}
setupPosthogJs()

/** Storybook global parameters. See https://storybook.js.org/docs/react/writing-stories/parameters#global-parameters */
export const parameters: Parameters = {
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
    // Make sure the msw service worker is started, and reset the handlers to defaults.
    withKea,
    // Allow us to time travel to ensure our stories don't change over time.
    // To mock a date for a story, set the `mockDate` parameter.
    withMockDate,
    // Allow us to easily set feature flags in stories.
    withFeatureFlags,
    // Set theme from global context
    withTheme,
    // Set the page URL
    withPageUrl,
]

const preview: Preview = {
    parameters: {
        actions: { argTypesRegex: '^on[A-Z].*' },
        controls: {
            matchers: {
                color: /(background|color)$/i,
                date: /Date$/,
            },
        },
        docs: {
            page: () => (
                <>
                    <Title />
                    <Subtitle />
                    <Description />
                    <Primary />
                    <Controls />
                    <Stories />
                </>
            ),
        },
    },
    globalTypes: {
        theme: {
            description: '',
            defaultValue: 'light',
            toolbar: {
                title: 'Theme',
                items: [
                    { value: 'light', icon: 'sun', title: 'Light' },
                    { value: 'dark', icon: 'moon', title: 'Dark' },
                ],
                // change the title based on the selected value
                dynamicTitle: true,
            },
        },
    },
}

export default preview
