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

/**
 * The meter this session bills under. Every session bills exactly one, so no `snapshot_source`
 * buys a free recording.
 *
 * Anything other than `mobile` is a web recording, including a value no SDK sends. Nothing between
 * the SDK and here validates the field, so matching `web` exactly would let any other string bill
 * nowhere. The report does match it exactly, and bills a mobile recording only from four named
 * libraries, so it bills neither meter for a session outside those values. Those are holes on its
 * side rather than a contract to copy.
 *
 * The meter reads the first message processed for the session. The report instead reads the
 * earliest snapshot's metadata, so the two disagree if one session's messages disagree with each
 * other about their source, which no single client does.
 */
function billableMeter(snapshotSource: string | null): string {
    return snapshotSource === 'mobile' ? 'mobile_replay_recordings' : 'session_replay_recordings'
}

export function createRecordSessionUsageStep<T extends SessionUsageInput>(
    usageBatch?: UsageRecordBatch
): ProcessingStep<Recordable<T>, Recordable<T>> {
    return function recordSessionUsage(value): Promise<PipelineResult<Recordable<T>>> {
        if (value.isNewSession) {
            const meter = billableMeter(value.parsedMessage.snapshot_source)
            const captureTimestampMs = value.headers.now?.getTime()
            usageBatch?.add(
                value.team.teamId,
                meter,
                value.headers.session_id,
                1,
                undefined,
                Number.isFinite(captureTimestampMs) ? captureTimestampMs : undefined
            )
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
