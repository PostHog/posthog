import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { initKeaTests } from '~/test/init'

import { CodeCanvasLink } from './CodeCanvasLink'

describe('CodeCanvasLink', () => {
    const replace = jest.fn()

    beforeEach(() => {
        replace.mockReset()
        // jsdom refuses a real navigation, so stand in a location whose replace we can read back.
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { ...window.location, replace },
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
            /^\/project\/7\/canvases\/canvas-1$/,
        ],
    ])('opens the canvas in the web app for %s', (_, path, expectedPath) => {
        router.actions.push(path)
        render(
            <Provider>
                <CodeCanvasLink channelId="channel-1" dashboardId="canvas-1" />
            </Provider>
        )

        expect(replace).toHaveBeenCalledWith(expect.stringMatching(expectedPath))
    })
})
