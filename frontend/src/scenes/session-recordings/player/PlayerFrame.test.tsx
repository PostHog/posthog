import '@testing-library/jest-dom'

import { act, fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { PlayerFrame } from './PlayerFrame'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

describe('PlayerFrame', () => {
    const logicProps = { sessionRecordingId: '1', playerKey: 'player-frame-test' }

    beforeEach(() => {
        setupSessionRecordingTest()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.REPLAY_PLAYER_OWN_DOCUMENT], {
            [FEATURE_FLAGS.REPLAY_PLAYER_OWN_DOCUMENT]: true,
        })
    })

    function renderPlayerFrame(): { container: HTMLElement; iframe: HTMLIFrameElement } {
        const { container } = render(
            <Provider>
                <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                    <PlayerFrame />
                </BindLogic>
            </Provider>
        )
        const iframe = container.querySelector('iframe.PlayerFrame__document')
        if (!(iframe instanceof HTMLIFrameElement)) {
            throw new Error('the flag-on player did not render its frame')
        }
        return { container, iframe }
    }

    it('mounts the player on the frame document once the frame loads', () => {
        const { iframe } = renderPlayerFrame()
        const frameDocument = iframe.contentDocument!
        frameDocument.open()
        frameDocument.write('<div id="player-frame-content"></div>')
        frameDocument.close()

        fireEvent.load(iframe)

        expect(sessionRecordingPlayerLogic(logicProps).values.rootFrame).toBe(
            frameDocument.getElementById('player-frame-content')
        )
        // The frame is same-origin, so any script permission added here runs as the app.
        expect(iframe).toHaveAttribute('sandbox', 'allow-same-origin')
    })

    // Firefox fires load for the frame's initial about:blank document, which has no mount node.
    // The shell document is still on its way, so the frame must keep its chance to load.
    it('keeps the frame and reports nothing when the blank first document loads', () => {
        const captureSpy = jest.spyOn(posthog, 'captureException')
        const { container, iframe } = renderPlayerFrame()
        // jsdom does not load the frame's src, so its document already carries the shell URL.
        Object.defineProperty(iframe.contentDocument!, 'URL', { value: 'about:blank' })

        fireEvent.load(iframe)

        expect(container.querySelector('iframe.PlayerFrame__document')).toBe(iframe)
        expect(container.querySelector('div.PlayerFrame__content')).toBeNull()
        expect(captureSpy).not.toHaveBeenCalled()
    })

    // A same-origin error page, a login redirect, or a browser network-error page all fire load
    // with a document that has no mount node. The frame gets retried before the player falls back
    // to the app document. Each retry records what the frame showed, and only the fallback is an exception.
    it('retries a frame that loads without a mount node, then falls back to the app document', () => {
        jest.useFakeTimers()
        try {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const captureExceptionSpy = jest.spyOn(posthog, 'captureException')
            const { container, iframe } = renderPlayerFrame()

            fireEvent.load(iframe)
            expect(container.querySelector('iframe')).toBe(iframe)
            act(() => {
                jest.advanceTimersByTime(1000)
            })
            expect(iframe).toHaveAttribute('src', '/replay_player_frame/index.html?retry=1')

            // A browser error page is cross-origin to the app, so the frame's document is unreadable.
            Object.defineProperty(iframe, 'contentDocument', { value: null, configurable: true })
            fireEvent.load(iframe)
            act(() => {
                jest.advanceTimersByTime(2000)
            })
            expect(iframe).toHaveAttribute('src', '/replay_player_frame/index.html?retry=2')

            fireEvent.load(iframe)

            expect(container.querySelector('iframe')).toBeNull()
            const fallback = container.querySelector('div.PlayerFrame__content')
            expect(fallback).not.toBeNull()
            expect(sessionRecordingPlayerLogic(logicProps).values.rootFrame).toBe(fallback)
            expect(
                captureSpy.mock.calls
                    .filter(([event]) => event === 'replay player frame load retried')
                    .map(([, properties]) => [properties?.attempt, properties?.frameDocumentReadable])
            ).toEqual([
                [1, true],
                [2, false],
            ])
            expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
            expect(captureExceptionSpy.mock.calls[0][1]).toMatchObject({ attempt: 3, frameDocumentReadable: false })
        } finally {
            jest.useRealTimers()
        }
    })

    // A frame cannot load while the browser is offline, and the app-document fallback needs no network,
    // so the player falls back at once instead of waiting for a connection that may not come back.
    it('falls back to the app document without a retry while the browser is offline', () => {
        const onLine = jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
        jest.useFakeTimers()
        try {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const captureExceptionSpy = jest.spyOn(posthog, 'captureException')
            const { container, iframe } = renderPlayerFrame()

            fireEvent.load(iframe)
            act(() => {
                jest.advanceTimersByTime(10000)
            })

            expect(container.querySelector('iframe')).toBeNull()
            const fallback = container.querySelector('div.PlayerFrame__content')
            expect(fallback).not.toBeNull()
            expect(sessionRecordingPlayerLogic(logicProps).values.rootFrame).toBe(fallback)
            expect(captureSpy).not.toHaveBeenCalledWith('replay player frame load retried', expect.anything())
            expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
            expect(captureExceptionSpy.mock.calls[0][1]).toMatchObject({ attempt: 1, browserOnline: false })
        } finally {
            jest.useRealTimers()
            onLine.mockRestore()
        }
    })
})
