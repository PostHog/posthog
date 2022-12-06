import { initKeaTests } from '~/test/init'
import { expectLogic } from 'kea-test-utils'
import { sessionRecodingFilePlaybackLogic } from './sessionRecodingFilePlaybackLogic'

describe('sessionRecodingFilePlaybackLogic', () => {
    let logic: ReturnType<typeof sessionRecodingFilePlaybackLogic.build>

    beforeEach(() => {
        initKeaTests()
    })

    describe('file-playback logic', () => {
        beforeEach(() => {
            logic = sessionRecodingFilePlaybackLogic()
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
