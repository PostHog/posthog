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

// The SDKs that record mobile replay. Only used to read the source of a session that did not
// send one: an older SDK from this list sends no `snapshot_source`, and its recording is mobile.
const MOBILE_LIBRARIES = new Set(['posthog-ios', 'posthog-android', 'posthog-react-native', 'posthog-flutter'])

/**
 * The meter this session bills under. Every session bills exactly one, so no combination of
 * `snapshot_source` and `snapshot_library` buys a free recording.
 *
 * A session that sends a source is billed on it, and anything other than `mobile` is a web
 * recording. Nothing between the SDK and here validates that field, so matching `web` exactly
 * would let any other string bill nowhere. The report matches both values exactly, and bills a
 * mobile recording only from the libraries above, which is why it bills neither meter for a
 * session outside those values. Those are holes on its side rather than a contract to copy.
 *
 * The meter reads the first message processed for the session. The report instead reads the
 * earliest snapshot's metadata, so the two disagree if one session's messages disagree with each
 * other about their source or library, which no single client does.
 */
function billableMeter(snapshotSource: string | null, snapshotLibrary: string | null): string {
    const source = snapshotSource || (MOBILE_LIBRARIES.has(snapshotLibrary || '') ? 'mobile' : 'web')
    return source === 'mobile' ? 'mobile_replay_recordings' : 'session_replay_recordings'
}

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(value): Promise<PipelineResult<Recordable<T>>> {
        if (value.isNewSession) {
            const meter = billableMeter(value.parsedMessage.snapshot_source, value.parsedMessage.snapshot_library)
            usageBatch?.add(value.team.teamId, meter, value.headers.session_id)
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
