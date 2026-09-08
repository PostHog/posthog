import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { setupSessionRecordingTest } from '../player/__mocks__/test-setup'
import { sessionRecordingDataCoordinatorLogic } from '../player/sessionRecordingDataCoordinatorLogic'
import { sessionRecordingFilePlaybackSceneLogic } from './sessionRecordingFilePlaybackSceneLogic'

const exportedRecording = {
    id: 'exported-recording',
    person: undefined,
    snapshots: [
        { windowId: '1', timestamp: 1000, type: 2, data: {} },
        { windowId: '1', timestamp: 3000, type: 2, data: {} },
    ],
} as any

describe('sessionRecordingFilePlaybackLogic', () => {
    let logic: ReturnType<typeof sessionRecordingFilePlaybackSceneLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest()
        logic = sessionRecordingFilePlaybackSceneLogic()
        logic.mount()
    })

    it('should generate a new playerKey on load', () => {
        expectLogic(logic).toMatchValues({
            playerProps: {
                sessionRecordingId: '',
                playerKey: 'file-playback-empty',
            },
        })

        logic.actions.loadFromFileSuccess({} as any)
        const playerProps = logic.values.playerProps
        expect(playerProps.playerKey).toMatch(/^file-playback-.{36}$/)

        logic.actions.loadFromFileSuccess({} as any)
        expect(playerProps.playerKey).not.toEqual(logic.values.playerProps.playerKey)
    })

    it('gives the recording to a player that mounts one second late', async () => {
        jest.useFakeTimers()
        try {
            logic.actions.loadFromFileSuccess(exportedRecording)
            await jest.advanceTimersByTimeAsync(1000)

            const dataLogic = sessionRecordingDataCoordinatorLogic(logic.values.playerProps)
            dataLogic.mount()
            await jest.advanceTimersByTimeAsync(100)

            expect(dataLogic.values.sessionPlayerMetaData?.id).toEqual('exported-recording')
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([
        ['the recording is reset', (): void => logic.actions.resetSessionRecording()],
        ['the scene is left', (): void => logic.unmount()],
    ])('says nothing when %s while the player is still mounting', async (_, interrupt) => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        jest.useFakeTimers()
        try {
            logic.actions.loadFromFileSuccess(exportedRecording)
            await jest.advanceTimersByTimeAsync(100)
            interrupt()
            await jest.advanceTimersByTimeAsync(2100)

            expect(errorToast).not.toHaveBeenCalled()
        } finally {
            jest.useRealTimers()
            errorToast.mockRestore()
        }
    })

    it('reports a message when the player never mounts', async () => {
        const errorToast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '')
        jest.useFakeTimers()
        try {
            logic.actions.loadFromFileSuccess(exportedRecording)
            await jest.advanceTimersByTimeAsync(2100)

            expect(errorToast).toHaveBeenCalledWith(
                'The player did not start in time. Please try loading the file again.'
            )
        } finally {
            jest.useRealTimers()
            errorToast.mockRestore()
        }
    })
})
