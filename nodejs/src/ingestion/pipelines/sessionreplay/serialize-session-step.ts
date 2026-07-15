import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRef } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import {
    ExtractedConsoleLogs,
    extractConsoleLogs,
} from '~/ingestion/pipelines/sessionreplay/sessions/session-console-log-recorder'
import {
    SerializedSessionData,
    serializeSessionData,
} from '~/ingestion/pipelines/sessionreplay/sessions/snappy-session-recorder'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

export interface SerializeSessionStepInput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
    retentionPeriod: RetentionPeriod
    sessionKey: SessionKey
}

export interface SerializeSessionStepOutput {
    session: SessionRef
    data: SerializedSessionData
    logs: ExtractedConsoleLogs
}

/**
 * Derives the per-message record data from a parsed message: the session it belongs to (with the
 * retention and encryption key resolved upstream), the serialized session block chunks, and the
 * extracted console logs. Pure business logic — the cycle reducer aggregates the result into the
 * session state without looking at the raw events again.
 */
export function createSerializeSessionStep<T extends SerializeSessionStepInput>(): ProcessingStep<
    T,
    T & SerializeSessionStepOutput
> {
    return function serializeSessionStep(input) {
        const { team, parsedMessage, retentionPeriod, sessionKey } = input
        const session: SessionRef = {
            teamId: team.teamId,
            sessionId: parsedMessage.session_id,
            partition: parsedMessage.metadata.partition,
            retentionPeriod,
            sessionKey,
        }
        return Promise.resolve(
            ok({
                ...input,
                session,
                data: serializeSessionData(parsedMessage),
                logs: extractConsoleLogs({ team, message: parsedMessage }),
            })
        )
    }
}
