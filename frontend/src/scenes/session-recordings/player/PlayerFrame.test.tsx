import '@testing-library/jest-dom'

import { fireEvent, render } from '@testing-library/react'
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
    })

    // A same-origin error page, a login redirect, or a browser network-error page all fire load
    // with a document that has no mount node. The player must not stay blank with no report.
    it('falls back to the app document and reports it when the frame loads without a mount node', () => {
        const captureSpy = jest.spyOn(posthog, 'captureException')
        const { container, iframe } = renderPlayerFrame()

        fireEvent.load(iframe)

        expect(container.querySelector('iframe')).toBeNull()
        const fallback = container.querySelector('div.PlayerFrame__content')
        expect(fallback).not.toBeNull()
        expect(sessionRecordingPlayerLogic(logicProps).values.rootFrame).toBe(fallback)
        expect(captureSpy).toHaveBeenCalledTimes(1)
    })
})
