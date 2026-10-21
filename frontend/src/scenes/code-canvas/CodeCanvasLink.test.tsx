import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import { CodeCanvasLink } from './CodeCanvasLink'

describe('CodeCanvasLink', () => {
    beforeEach(() => {
        // jsdom refuses a real navigation, so stand in a location whose href we can read back.
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...window.location, href: '' },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        ['an unscoped link, in the current project', '/code/canvas/channel-1/canvas-1', /\/canvases\/canvas-1$/],
        [
            'a project-scoped link, in that project',
            '/project/7/code/canvas/channel-1/canvas-1',
            /\/project\/7\/canvases\/canvas-1$/,
        ],
    ])('links to the canvas in the browser for %s', (_, path, expectedHref) => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true })
        router.actions.push(path)
        render(
            <Provider>
                <CodeCanvasLink channelId="channel-1" dashboardId="canvas-1" />
            </Provider>
        )

        expect(window.location.href).toBe('posthog-code://canvas/channel-1/canvas-1')
        expect(screen.getByText('Open in browser').closest('a')).toHaveAttribute(
            'href',
            expect.stringMatching(expectedHref)
        )
    })

    it('hides the browser link when the web canvas would show not found', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(
            <Provider>
                <CodeCanvasLink channelId="channel-1" dashboardId="canvas-1" />
            </Provider>
        )

        expect(screen.queryByText('Open in browser')).not.toBeInTheDocument()
    })
})
