import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { ToastContainer } from 'react-toastify'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { LiveStreamError, liveEventsLogic } from './liveEventsLogic'
import { liveEventsTableSceneLogic } from './liveEventsTableSceneLogic'

const TRANSPORT_ERROR: LiveStreamError = {
    message: 'Lost the connection to the live event stream. Trying to reconnect.',
    retrying: true,
}

const FATAL_ERROR: LiveStreamError = {
    message: 'The live event stream failed with error 502. Try again, and contact us if it keeps happening.',
    retrying: false,
}

describe('liveEventsTableSceneLogic', () => {
    let logic: ReturnType<typeof liveEventsLogic.build>
    let sceneLogic: ReturnType<typeof liveEventsTableSceneLogic.build>
    let streamSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        streamSpy = jest.spyOn(api, 'stream').mockResolvedValue(undefined as any)
        logic = liveEventsLogic()
        logic.mount()
        sceneLogic = liveEventsTableSceneLogic()
        sceneLogic.mount()
    })

    afterEach(() => {
        sceneLogic.unmount()
        logic.unmount()
        streamSpy.mockRestore()
        lemonToast.dismiss()
        cleanup()
    })

    it('replaces the reconnect message when the retry turns out to be fatal', async () => {
        render(<ToastContainer />)

        logic.actions.streamErrored(TRANSPORT_ERROR)
        await waitFor(() => expect(screen.getByText(TRANSPORT_ERROR.message)).toBeInTheDocument())

        logic.actions.streamErrored(FATAL_ERROR)

        await waitFor(() => expect(screen.getByText(FATAL_ERROR.message)).toBeInTheDocument())
        expect(screen.queryByText(TRANSPORT_ERROR.message)).not.toBeInTheDocument()
    })

    it.each([
        ['the first healthy open', false],
        ['recovering from an earlier error', true],
    ])('still reports a failure that follows %s', async (_label, hadEarlierError) => {
        render(<ToastContainer />)

        if (hadEarlierError) {
            logic.actions.streamErrored(TRANSPORT_ERROR)
            await waitFor(() => expect(screen.getByText(TRANSPORT_ERROR.message)).toBeInTheDocument())
        }
        logic.actions.streamConnected()

        logic.actions.streamErrored(FATAL_ERROR)

        await waitFor(() => expect(screen.getByText(FATAL_ERROR.message)).toBeInTheDocument())
    })
})
