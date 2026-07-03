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

    const element = (teamId: number, sessionId: string, isNewSession: boolean, blocked: boolean): Resolved<Base> => {
        const base = {
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            isNewSession,
        }
        return (blocked
            ? { ...base, blocked: true }
            : { ...base, blocked: false, sessionKey: createMockSessionKey() }) as unknown as Resolved<Base>
    }

    const createStep = () => createMarkSeenStep(mockSessionTracker as unknown as SessionTracker)

    beforeEach(() => {
        jest.clearAllMocks()
        mockSessionTracker = { markSeen: jest.fn().mockResolvedValue(undefined) }
    })

    it('marks every new session seen (allowed and blocked) in one deduped call, then drops the blocked ones', async () => {
        const values = [
            element(1, 'allowed-new', true, false),
            element(1, 'allowed-new', true, false),
            element(1, 'blocked-new', true, true),
            element(1, 'existing', false, false),
        ]

        const results = await createStep()(values)

        // One markSeen for the whole batch — both new sessions (allowed and blocked), deduped; the
        // existing one is excluded. Marking the blocked one is what stops it being re-counted next batch.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(
            new SessionSet().add(1, 'allowed-new').add(1, 'blocked-new')
        )
        // Blocked session is dropped; the rest pass through.
        expect(results.map((r) => r.type)).toEqual([
            PipelineResultType.OK,
            PipelineResultType.OK,
            PipelineResultType.DROP,
            PipelineResultType.OK,
        ])
    })

    it('marks an empty set when the batch has no new sessions', async () => {
        await createStep()([element(1, 'a', false, false), element(2, 'b', false, true)])

        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet())
    })

    it('preserves the resolved key on the passed-through allowed sessions', async () => {
        const results = await createStep()([element(1, 'a', true, false)])

        expect(isOkResult(results[0]) && !results[0].value.blocked ? results[0].value.sessionKey : null).not.toBeNull()
    })
})
