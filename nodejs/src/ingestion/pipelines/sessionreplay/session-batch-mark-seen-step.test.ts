import { isOkResult } from '~/ingestion/framework/results'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionReplayHeaders } from './pipeline-types'
import { createMarkSeenStep } from './session-batch-mark-seen-step'
import { SessionTracker } from './sessions/session-tracker'

describe('createMarkSeenStep', () => {
    let mockSessionTracker: jest.Mocked<Pick<SessionTracker, 'markSeen'>>

    const element = (
        teamId: number,
        sessionId: string,
        isNewSession: boolean
    ): { team: TeamForReplay; headers: SessionReplayHeaders; isNewSession: boolean } =>
        ({
            team: { teamId, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true },
            headers: { token: 'token', session_id: sessionId, distinct_id: 'distinct-1' },
            isNewSession,
        }) as unknown as { team: TeamForReplay; headers: SessionReplayHeaders; isNewSession: boolean }

    const createStep = () => createMarkSeenStep(mockSessionTracker as unknown as SessionTracker)

    beforeEach(() => {
        jest.clearAllMocks()
        mockSessionTracker = { markSeen: jest.fn().mockResolvedValue(undefined) }
    })

    it('marks only the new sessions seen, deduped, in one call and passes every element through', async () => {
        const values = [element(1, 'new', true), element(1, 'new', true), element(1, 'existing', false)]

        const results = await createStep()(values)

        // One markSeen for the whole batch; the repeated new session is deduped, the existing one excluded.
        expect(mockSessionTracker.markSeen).toHaveBeenCalledTimes(1)
        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet().add(1, 'new'))
        expect(results.every(isOkResult)).toBe(true)
        expect(results.map((r) => (isOkResult(r) ? r.value : null))).toEqual(values)
    })

    it('marks an empty set when the batch has no new sessions', async () => {
        await createStep()([element(1, 'a', false), element(2, 'b', false)])

        expect(mockSessionTracker.markSeen).toHaveBeenCalledWith(new SessionSet())
    })
})
