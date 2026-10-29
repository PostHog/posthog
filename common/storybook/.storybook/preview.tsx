import '~/styles'

import { Controls, Description, Primary, Stories, Subtitle, Title } from '@storybook/addon-docs/blocks'
import type { Preview } from '@storybook/react'
import { configure as configureTestingLibrary } from '@testing-library/dom'

import { apiHostOrigin } from 'lib/utils/apiHost'

import { loadPostHogJS } from '~/loadPostHogJS'
import { worker } from '~/mocks/browser'

import { getStorybookAppContext } from './app-context'
import { withChartCanvasSnapshot } from './decorators/withChartCanvasSnapshot'
import { withFeatureFlags } from './decorators/withFeatureFlags'
import { withKea } from './decorators/withKea'
import { withMockDate } from './decorators/withMockDate'
import { withPageUrl } from './decorators/withPageUrl'
import { withTheme } from './decorators/withTheme'

// Play functions start as soon as React commits the first render, but scene-based stories keep
// loading data for several seconds after that — longer on a busy CI runner. testing-library's
// default 1s findBy*/waitFor timeout loses that race and fails plays spuriously, so give every
// story a load-tolerant default budget instead of making each play pass its own timeout.
configureTestingLibrary({ asyncUtilTimeout: 15000 })

const setupMsw = (): void => {
    // Make sure the msw worker is started
    worker.start({
        quiet: true,
        onUnhandledRequest(request, print) {
            // MSW warns on all unhandled requests, but we don't necessarily care
            const pathAllowList = ['/images/']
            const { pathname } = new URL(request.url)

            if (pathAllowList.some((path) => pathname.startsWith(path))) {
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

// Canvas charts measure text at paint time and never repaint when fonts finish loading, so hold
// every story's render until the app fonts (the set the visual-regression runner preloads) are in.
const loaders: Preview['loaders'] = [
    async () => {
        await Promise.all(
            ['400', '500', '700', '800'].flatMap((weight) => [
                document.fonts.load(`${weight} 16px Inter`),
                document.fonts.load(`${weight} 16px RoundHog`),
            ])
        )
            .then(() => document.fonts.ready)
            .catch(() => undefined)
        return {}
    },
]

// Setup storybook global decorators. See https://storybook.js.org/docs/react/writing-stories/decorators#global-decorators
const decorators: Preview['decorators'] = [
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
    // Suppress quill-charts canvas painting for snapshot stories that opt in via testOptions.skipCanvasDraw
    withChartCanvasSnapshot,
]

const preview: Preview = {
    loaders,
    decorators,
    parameters: {
        actions: { argTypesRegex: '^on[A-Z].*' },
        // We don't want axe-core tests in visual review
        a11y: { test: 'off' },
        controls: {
            matchers: {
                color: /(background|color)$/i,
                date: /Date$/,
            },
        },
        options: {
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
        docs: {
            source: { state: 'closed' },
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
