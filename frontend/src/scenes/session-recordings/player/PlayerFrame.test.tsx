import '@testing-library/jest-dom'

import { act, fireEvent, render } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import posthog from 'posthog-js'

import { SessionPlayerState } from '~/types'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { PlayerFrame } from './PlayerFrame'
import { sessionRecordingPlayerLogic } from './sessionRecordingPlayerLogic'

describe('PlayerFrame', () => {
    const logicProps = { sessionRecordingId: '1', playerKey: 'player-frame-test' }

    beforeEach(() => {
        setupSessionRecordingTest()
    })

    function renderPlayerFrame(): HTMLIFrameElement {
        const { container } = render(
            <Provider>
                <BindLogic logic={sessionRecordingPlayerLogic} props={logicProps}>
                    <PlayerFrame />
                </BindLogic>
            </Provider>
        )
        const iframe = container.querySelector('iframe.PlayerFrame__document')
        if (!(iframe instanceof HTMLIFrameElement)) {
            throw new Error('the player did not render its frame')
        }
        // jsdom leaves the frame document mid-load, and the player judges a document that finished loading.
        Object.defineProperty(iframe.contentDocument!, 'readyState', { value: 'complete', configurable: true })
        return iframe
    }

    it('mounts the player on the frame document once the frame loads', () => {
        const iframe = renderPlayerFrame()
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

    // A load event that never arrives used to leave rrweb with nowhere to mount, so the player
    // showed an empty rectangle for as long as the tab stayed open. The timeout feeds the same
    // failure action as a load without a mount node, so the first timeout retries the frame and
    // the retry flow reaches the player's error state.
    it('retries the frame when the load event never arrives, then shows the player error', () => {
        jest.useFakeTimers()
        try {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const captureExceptionSpy = jest.spyOn(posthog, 'captureException')
            const iframe = renderPlayerFrame()
            const container = iframe.parentElement!

            // The load never fires. The 10s timeout reports the first failure, which schedules a retry.
            act(() => {
                jest.advanceTimersByTime(10000)
            })
            expect(container.querySelector('iframe')).toBe(iframe)
            expect(captureSpy).toHaveBeenCalledWith(
                'replay player frame load retried',
                expect.objectContaining({ attempt: 1 })
            )

            // The retry changes the src, and the reloaded frame's load also never fires. The frame
            // gets MAX_PLAYER_FRAME_LOAD_RETRIES retries, so failures 1 and 2 retry and failure 3
            // reaches the error state.
            act(() => {
                jest.advanceTimersByTime(1000)
            })
            expect(iframe).toHaveAttribute('src', '/replay_player_frame/index.html?retry=1')

            act(() => {
                jest.advanceTimersByTime(10000)
            })
            expect(captureSpy).toHaveBeenCalledWith(
                'replay player frame load retried',
                expect.objectContaining({ attempt: 2 })
            )

            act(() => {
                jest.advanceTimersByTime(2000)
            })
            expect(iframe).toHaveAttribute('src', '/replay_player_frame/index.html?retry=2')

            act(() => {
                jest.advanceTimersByTime(10000)
            })

            expect(sessionRecordingPlayerLogic(logicProps).values.currentPlayerState).toBe(SessionPlayerState.ERROR)
            expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        } finally {
            jest.useRealTimers()
        }
    })

    // Firefox fires load for the frame's initial about:blank document, and a load event for a previous
    // document arrives while the shell is still parsing. Neither has a mount node, and neither is a failure.
    it.each([
        ['the blank first document loads', 'about:blank', 'complete'],
        ['a load arrives while the shell is still parsing', '/replay_player_frame/index.html', 'loading'],
    ])('reports nothing when %s', (_, url, readyState) => {
        const captureSpy = jest.spyOn(posthog, 'capture')
        const captureExceptionSpy = jest.spyOn(posthog, 'captureException')
        const iframe = renderPlayerFrame()
        // jsdom does not load the frame's src, so its document already carries the shell URL.
        Object.defineProperty(iframe.contentDocument!, 'URL', { value: url })
        Object.defineProperty(iframe.contentDocument!, 'readyState', { value: readyState, configurable: true })

        fireEvent.load(iframe)

        expect(captureExceptionSpy).not.toHaveBeenCalled()
        expect(captureSpy).not.toHaveBeenCalledWith('replay player frame load retried', expect.anything())
    })

    // A same-origin error page, a login redirect, or a browser network-error page all fire load
    // with a document that has no mount node. The frame gets retried before the player shows its error
    // state. Each retry records what the frame showed, and only the last failure is an exception.
    it('retries a frame that loads without a mount node, then shows the player error', () => {
        jest.useFakeTimers()
        try {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const captureExceptionSpy = jest.spyOn(posthog, 'captureException')
            const iframe = renderPlayerFrame()
            const logic = sessionRecordingPlayerLogic(logicProps)

            fireEvent.load(iframe)
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
            expect(logic.values.currentPlayerState).not.toBe(SessionPlayerState.ERROR)

            fireEvent.load(iframe)

            expect(logic.values.currentPlayerState).toBe(SessionPlayerState.ERROR)
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

    // A frame cannot load while the browser is offline, so the player shows its error at once instead of
    // staying blank while it waits for a connection that may not come back.
    it('shows the player error without a retry while the browser is offline', () => {
        const onLine = jest.spyOn(navigator, 'onLine', 'get').mockReturnValue(false)
        jest.useFakeTimers()
        try {
            const captureSpy = jest.spyOn(posthog, 'capture')
            const captureExceptionSpy = jest.spyOn(posthog, 'captureException')
            const iframe = renderPlayerFrame()

            fireEvent.load(iframe)
            act(() => {
                jest.advanceTimersByTime(10000)
            })

            expect(sessionRecordingPlayerLogic(logicProps).values.currentPlayerState).toBe(SessionPlayerState.ERROR)
            expect(iframe).toHaveAttribute('src', '/replay_player_frame/index.html')
            expect(captureSpy).not.toHaveBeenCalledWith('replay player frame load retried', expect.anything())
            expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
            expect(captureExceptionSpy.mock.calls[0][1]).toMatchObject({ attempt: 1, browserOnline: false })
        } finally {
            jest.useRealTimers()
            onLine.mockRestore()
        }
    })
})
