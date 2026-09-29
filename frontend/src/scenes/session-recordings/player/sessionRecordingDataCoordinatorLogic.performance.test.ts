import { readFileSync } from 'fs'
import { expectLogic } from 'kea-test-utils'
import { HttpResponse } from 'msw'
import { join } from 'path'

import { uuid } from 'lib/utils/dom'
import { sessionRecordingDataCoordinatorLogic } from 'scenes/session-recordings/player/sessionRecordingDataCoordinatorLogic'

import { setupSessionRecordingTest } from './__mocks__/test-setup'
import { snapshotDataLogic } from './snapshotDataLogic'

const pathForKeyZero = join(__dirname, './__mocks__/perf-snapshot-key0.jsonl')
const pathForKeyOne = join(__dirname, './__mocks__/perf-snapshot-key1.jsonl')

const readFileContents = (path: string): string => {
    return readFileSync(path, 'utf-8')
}

const keyZero = readFileContents(pathForKeyZero)
const keyOne = readFileContents(pathForKeyOne)

jest.setTimeout(120_000)

describe('sessionRecordingDataCoordinatorLogic performance', () => {
    let logic: ReturnType<typeof sessionRecordingDataCoordinatorLogic.build>
    let snapshotLogic: ReturnType<typeof snapshotDataLogic.build>

    beforeEach(() => {
        setupSessionRecordingTest({
            snapshotSources: [
                {
                    source: 'blob_v2',
                    start_timestamp: '2025-05-14T15:37:16.454000Z',
                    end_timestamp: '2025-05-14T15:37:18.379000Z',
                    blob_key: '0',
                },
                {
                    source: 'blob_v2',
                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                    blob_key: '1',
                },
            ],
            getMocks: {
                '/api/environments/:team_id/session_recordings/:id/snapshots': ({ request }) => {
                    const url = new URL(request.url)
                    if (url.searchParams.get('source') === 'blob_v2') {
                        const key = url.searchParams.get('blob_key')
                        const contents = key === '0' ? keyZero : keyOne
                        return new HttpResponse(contents)
                    }

                    return [
                        200,
                        {
                            sources: [
                                {
                                    source: 'blob_v2',
                                    start_timestamp: '2025-05-14T15:37:16.454000Z',
                                    end_timestamp: '2025-05-14T15:37:18.379000Z',
                                    blob_key: '0',
                                },
                                {
                                    source: 'blob_v2',
                                    start_timestamp: '2025-05-14T15:37:18.897000Z',
                                    end_timestamp: '2025-05-14T15:42:18.378000Z',
                                    blob_key: '1',
                                },
                            ],
                        },
                    ]
                },
            },
        })
    })

    describe('loading snapshots', () => {
        const setupLogic = (): void => {
            const props = {
                sessionRecordingId: uuid(),
                blobV2PollingDisabled: true,
            }
            logic = sessionRecordingDataCoordinatorLogic(props)
            snapshotLogic = snapshotDataLogic(props)
            logic.mount()
            // Most of these tests assume the metadata is being loaded upfront which is the typical case
            logic.actions.loadRecordingMeta()
        }

        it('loads all data', async () => {
            setupLogic()

            await expectLogic(logic, () => {
                logic.actions.loadSnapshots()
            })
                .toDispatchActions([
                    'loadSnapshots',
                    'loadSnapshotSources',
                    'loadRecordingMetaSuccess',
                    snapshotLogic.actionTypes.loadSnapshotSourcesSuccess,
                    snapshotLogic.actionTypes.loadSnapshotsForSourceSuccess,
                    'reportUsageIfFullyLoaded',
                ])
                .toFinishListeners()

            expect(Object.keys(logic.values.sessionPlayerData.snapshotsByWindowId)).toHaveLength(1)

            logic.unmount()
        })
    })
})
