import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { ok } from '~/ingestion/framework/results'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { NewSessionFlag } from './pipeline-types'
import { SessionTracker } from './sessions/session-tracker'
import { SessionReplayHeaders } from './validate-headers-step'

/**
 * Record-phase batch step: mark every new session in the batch as seen, in one Redis pipeline, now that
 * each session's key has been durably resolved upstream. Marking earlier — before the key exists —
 * would, on a key-resolution retry, make a session read as existing and fetch a key that was never
 * generated, recording cleartext. Only sessions that survived key resolution reach this step; blocked
 * sessions were already marked when they were dropped (see {@link createTrackAndGateStep}).
 *
 * Pass-through: it records seen state and forwards every element unchanged. {@link SessionTracker.markSeen}
 * fails open, so this step never needs a retry wrapper.
 */
export function createMarkSeenStep<T extends { team: TeamForReplay; headers: SessionReplayHeaders } & NewSessionFlag>(
    sessionTracker: SessionTracker
): BatchProcessingStep<T, T> {
    return async function markSeenStep(values) {
        const newlySeen = new SessionSet()
        for (const value of values) {
            if (value.isNewSession) {
                newlySeen.add(value.team.teamId, value.headers.session_id)
            }
        }

        await sessionTracker.markSeen(newlySeen)

        return values.map((value) => ok(value))
    }
}
