import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { sessionRecordingFilePlaybackLogic } from './sessionRecordingFilePlaybackLogic'

describe('sessionRecordingFilePlaybackLogic', () => {
    let logic: ReturnType<typeof sessionRecordingFilePlaybackLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('file-playback logic', () => {
        beforeEach(() => {
            logic = sessionRecordingFilePlaybackLogic()
            logic.mount()
        })

        it('should generate a new playerKey on load', () => {
            expectLogic(logic).toMatchValues({
                playerKey: 'file-playback',
            })

            logic.actions.loadFromFileSuccess({} as any)
            const playerKey = logic.values.playerKey
            expect(playerKey).toMatch(/^file-playback-.{36}$/)

            logic.actions.loadFromFileSuccess({} as any)
            expect(playerKey).not.toEqual(logic.values.playerKey)
        })
    })
})
