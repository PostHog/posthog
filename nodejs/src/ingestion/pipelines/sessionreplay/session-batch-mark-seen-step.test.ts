import { PipelineResultType, isOkResult } from '~/ingestion/framework/results'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { NewSessionFlag, Resolved, SessionReplayHeaders } from './pipeline-types'
import { createMarkSeenStep } from './session-batch-mark-seen-step'
import { SessionTracker } from './sessions/session-tracker'

jest.mock('~/common/utils/logger', () => ({ logger: { debug: jest.fn() } }))

type Base = { team: TeamForReplay; headers: SessionReplayHeaders } & NewSessionFlag

describe('createMarkSeenStep', () => {
    let mockSessionTracker: jest.Mocked<Pick<SessionTracker, 'markSeen'>>

    const element = (
        teamId: number,
        sessionId: string,
        isNewSession: boolean,
        status: 'allowed' | 'blocked' | 'deleted'
    ): Resolved<Base> => {
        const base = {
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            isNewSession,
        }
        const resolved =
            status === 'allowed' ? { ...base, status, sessionKey: createMockSessionKey() } : { ...base, status }
        return resolved as unknown as Resolved<Base>
    }

    const createStep = () => createMarkSeenStep(mockSessionTracker as unknown as SessionTracker)

    beforeEach(() => {
        jest.clearAllMocks()
        mockSessionTracker = { markSeen: jest.fn().mockResolvedValue(undefined) }
    })

    it('marks every new session seen (allowed, blocked, deleted) in one deduped call, then drops the non-recorded ones', async () => {
        const values = [
            element(1, 'allowed-new', true, 'allowed'),
            element(1, 'allowed-new', true, 'allowed'),
            element(1, 'blocked-new', true, 'blocked'),
            element(1, 'deleted-new', true, 'deleted'),
            element(1, 'existing', false, 'allowed'),
        ]

        const results = await createStep()(values)

        // One markSeen for the whole batch — every new session (allowed, blocked AND deleted), deduped;
        // the existing one is excluded. Marking the blocked/deleted ones stops them being re-counted.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(
            new SessionSet().add(1, 'allowed-new').add(1, 'blocked-new').add(1, 'deleted-new')
        )
        // Blocked and deleted sessions are dropped; the allowed ones pass through.
        expect(results.map((r) => r.type)).toEqual([
            PipelineResultType.OK,
            PipelineResultType.OK,
            PipelineResultType.DROP,
            PipelineResultType.DROP,
            PipelineResultType.OK,
        ])
    })

    it('marks an empty set when the batch has no new sessions', async () => {
        await createStep()([element(1, 'a', false, 'allowed'), element(2, 'b', false, 'blocked')])

        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet())
    })

    it('preserves the resolved key on the passed-through allowed sessions', async () => {
        const results = await createStep()([element(1, 'a', true, 'allowed')])

        expect(
            isOkResult(results[0]) && results[0].value.status === 'allowed' ? results[0].value.sessionKey : null
        ).not.toBeNull()
    })
})
