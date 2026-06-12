import { expectLogic } from 'kea-test-utils'

import { IngestionWarning } from 'scenes/data-management/ingestion-warnings/ingestionWarningsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { playerIngestionWarningsLogic } from './playerIngestionWarningsLogic'

describe('playerIngestionWarningsLogic', () => {
    let logic: ReturnType<typeof playerIngestionWarningsLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team_id/ingestion_warnings': {
                    results: [
                        {
                            type: 'replay_message_too_large',
                            lastSeen: '2026-06-12T10:00:00Z',
                            count: 2,
                            sparkline: [],
                            warnings: [
                                {
                                    type: 'replay_message_too_large',
                                    timestamp: '2026-06-12T10:00:00Z',
                                    details: { replayRecord: { session_id: 'session-1' } },
                                },
                                {
                                    type: 'replay_message_too_large',
                                    timestamp: '2026-06-12T10:00:00Z',
                                    details: { replayRecord: { session_id: 'other-session' } },
                                },
                            ],
                        },
                        {
                            type: 'cannot_merge_already_identified',
                            lastSeen: '2026-06-12T10:00:00Z',
                            count: 1,
                            sparkline: [],
                            warnings: [
                                {
                                    type: 'cannot_merge_already_identified',
                                    timestamp: '2026-06-12T10:00:00Z',
                                    details: {},
                                },
                            ],
                        },
                        {
                            // a forged prototype-key type must not match the phrase map
                            type: 'constructor',
                            lastSeen: '2026-06-12T10:00:00Z',
                            count: 1,
                            sparkline: [],
                            warnings: [
                                {
                                    type: 'constructor',
                                    timestamp: '2026-06-12T10:00:00Z',
                                    details: { sessionId: 'session-1' },
                                },
                            ],
                        },
                    ],
                },
            },
        })
        initKeaTests()
        logic = playerIngestionWarningsLogic({ sessionRecordingId: 'session-1' })
        logic.mount()
    })

    it('loads warnings and keeps only replay types for this session', async () => {
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.replayWarnings).toHaveLength(1)
        expect(logic.values.replayWarnings[0].type).toBe('replay_message_too_large')
        expect(logic.values.droppedDataPhrases).toEqual(['some data was too large to ingest'])
    })

    it('does not let a forged prototype-key warning type leak into the banner', async () => {
        await expectLogic(logic).toFinishAllListeners()

        const types = logic.values.replayWarnings.map((w: IngestionWarning) => w.type)
        expect(types).not.toContain('constructor')
        expect(logic.values.droppedDataPhrases).toEqual(['some data was too large to ingest'])
    })
})
