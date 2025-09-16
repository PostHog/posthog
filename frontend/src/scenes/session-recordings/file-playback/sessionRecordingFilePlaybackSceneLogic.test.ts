import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { sessionRecordingFilePlaybackSceneLogic } from './sessionRecordingFilePlaybackSceneLogic'

describe('sessionRecordingFilePlaybackLogic', () => {
    let logic: ReturnType<typeof sessionRecordingFilePlaybackSceneLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('file-playback logic', () => {
        beforeEach(() => {
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
    })
})
