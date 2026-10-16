import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    parseExportedSessionRecording,
    sessionRecordingFilePlaybackSceneLogic,
} from './sessionRecordingFilePlaybackSceneLogic'

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

    describe('parseExportedSessionRecording', () => {
        it.each([
            [
                '2022-12-02',
                {
                    snapshotsByWindowId: {
                        'window-a': [
                            { type: 2, data: {}, timestamp: 1000 },
                            { type: 3, data: {}, timestamp: 3000 },
                        ],
                        'window-b': [{ type: 2, data: {}, timestamp: 2000 }],
                    },
                },
            ],
            [
                '2023-04-28',
                {
                    id: '',
                    snapshots: [
                        { type: 2, data: {}, timestamp: 1000, windowId: 'window-a' },
                        { type: 2, data: {}, timestamp: 2000, windowId: 'window-b' },
                        { type: 3, data: {}, timestamp: 3000, windowId: 'window-a' },
                    ],
                },
            ],
        ])('maps window UUIDs in a %s export to integer window ids', (version, data) => {
            const parsed = parseExportedSessionRecording(JSON.stringify({ version, data }))

            expect(parsed.data.snapshots.map((s) => [s.timestamp, s.windowId])).toEqual([
                [1000, 1],
                [2000, 2],
                [3000, 1],
            ])
        })
    })
})
