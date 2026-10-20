import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

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

    it('links to the canvas in the browser for visitors who can open web canvases', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TODAY_RAIL_NAV]: true })
        render(
            <Provider>
                <CodeCanvasLink channelId="channel-1" dashboardId="canvas-1" />
            </Provider>
        )

        expect(window.location.href).toBe('posthog-code://canvas/channel-1/canvas-1')
        expect(screen.getByText('open it in your browser').closest('a')).toHaveAttribute(
            'href',
            expect.stringMatching(/\/canvases\/canvas-1$/)
        )
    })

    it('hides the browser link when the web canvas would show not found', () => {
        featureFlagLogic.actions.setFeatureFlags([], {})
        render(
            <Provider>
                <CodeCanvasLink channelId="channel-1" dashboardId="canvas-1" />
            </Provider>
        )

        expect(screen.queryByText('open it in your browser')).not.toBeInTheDocument()
    })
})
