import { expectLogic } from 'kea-test-utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { playerInspectorLogic } from 'scenes/session-recordings/player/inspector/playerInspectorLogic'
import { sessionRecordingDataLogic } from 'scenes/session-recordings/player/sessionRecordingDataLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

const playerLogicProps = { sessionRecordingId: '1', playerKey: 'playlist' }

describe('playerInspectorLogic', () => {
    let logic: ReturnType<typeof playerInspectorLogic.build>
    let dataLogic: ReturnType<typeof sessionRecordingDataLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                'api/environments/:team_id/session_recordings/1/': {},
                'api/projects/:team/notebooks/recording_comments': {
                    results: [
                        {
                            timeInRecording: 12,
                            comment: 'The comment',
                            notebookShortId: '12345',
                            notebookTitle: 'The notebook',
                            id: 'abcdefg',
                        },
                    ],
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()

        dataLogic = sessionRecordingDataLogic(playerLogicProps)
        dataLogic.mount()

        logic = playerInspectorLogic(playerLogicProps)
        logic.mount()
    })

    describe('item comments', () => {
        it('does not load comments without prompting', async () => {
            await expectLogic(logic).toMatchValues({
                sessionComments: null,
            })
        })

        it('reads comments from data logic', async () => {
            await expectLogic(dataLogic, () => {
                dataLogic.actions.maybeLoadRecordingMeta()
            }).toDispatchActions(['loadRecordingCommentsSuccess'])

            await expectLogic(logic).toMatchValues({
                sessionComments: [
                    {
                        timeInRecording: 12,
                        comment: 'The comment',
                        notebookShortId: '12345',
                        notebookTitle: 'The notebook',
                        id: 'abcdefg',
                    },
                ],
            })
        })
    })

    describe('setTrackedWindow', () => {
        it('starts with no tracked window', async () => {
            await expectLogic(logic, () => {
                logic.actions.setTrackedWindow(null as unknown as string)
            })
                .toDispatchActions(['setTrackedWindow'])
                .toMatchValues({
                    trackedWindow: null,
                })
        })

        it('can set tracked window', async () => {
            await expectLogic(logic).toMatchValues({
                trackedWindow: null,
            })
            await expectLogic(logic, () => {
                logic.actions.setTrackedWindow('nightly')
            })
                .toDispatchActions(['setTrackedWindow'])
                .toMatchValues({
                    trackedWindow: 'nightly',
                })
        })
    })
})
