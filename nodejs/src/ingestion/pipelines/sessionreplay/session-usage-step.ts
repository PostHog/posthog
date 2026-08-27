import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { PipelineResult, isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { ParsedMessageData } from './kafka/types'
import { SessionRecordingIngesterMetrics } from './metrics'
import { NewSessionFlag, Recordable, SessionReplayHeaders } from './pipeline-types'
import { TeamForReplay } from './teams/types'

type SessionUsageInput = {
    team: TeamForReplay
    headers: SessionReplayHeaders
    parsedMessage: ParsedMessageData
} & NewSessionFlag

// The report bills mobile replay only from the SDKs it lists, and counts a web recording
// and a mobile one under separate meters, so a mobile session is never both.
const BILLABLE_MOBILE_LIBRARIES = new Set(['posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'])

/**
 * The meter this session bills under, or null for neither.
 *
 * Web is the default rather than a third exact match on `snapshot_source`. Nothing between the SDK
 * and here validates that field, so matching `web` exactly would let any other string buy a free
 * recording. The report does match it exactly, which is a hole on its side, not a contract to copy.
 *
 * Both meters read the first message processed for the session. The report instead reads the
 * earliest snapshot's metadata, so the two disagree if one session's messages disagree with each
 * other about their source or library, which no single client does.
 */
function billableMeter(snapshotSource: string | null, snapshotLibrary: string | null): string | null {
    if (snapshotSource !== 'mobile') {
        return 'session_replay_recordings'
    }
    return BILLABLE_MOBILE_LIBRARIES.has(snapshotLibrary || '') ? 'mobile_replay_recordings' : null
}

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(value): Promise<PipelineResult<Recordable<T>>> {
        if (value.isNewSession) {
            const meter = billableMeter(value.parsedMessage.snapshot_source, value.parsedMessage.snapshot_library)
            if (meter) {
                usageBatch?.add(value.team.teamId, meter, value.headers.session_id)
            }
        }
        return Promise.resolve(ok(value))
    }
}

/**
 * Counts the new sessions that lose their flag before they can bill. The pipeline marks a session
 * seen before this step's message is parsed, so a first message that fails takes the flag with it:
 * a later valid message for the same session bills nothing, while the report still counts the
 * recording it produced. Marking later is not free — the mark sits after key resolution so a
 * recording is never written in cleartext — so measure how often this happens before paying for it.
 */
export function trackUnbilledNewSessions<T extends NewSessionFlag, U>(
    step: ProcessingStep<T, U>
): ProcessingStep<T, U> {
    return async function trackUnbilledNewSession(value): Promise<PipelineResult<U>> {
        const result = await step(value)
        if (value.isNewSession && !isOkResult(result)) {
            SessionRecordingIngesterMetrics.incrementUnbilledNewSession(result.reason)
        }
        return result
    }
}
