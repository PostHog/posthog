import { Message } from 'node-rdkafka'

import { parseKafkaHeaders } from '~/common/kafka/consumer'
import { isDevEnv } from '~/common/utils/env-utils'
import { logger } from '~/common/utils/logger'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import type { Team } from '~/types'

import { recordLogMessageDropped } from '../ingestion-otel-metrics'
import { INTERNAL_LOGS_HEADER } from '../internal-logs'
import {
    logMessageDroppedCounter,
    logsRecordsBytesExceedPayloadCounter,
    parseMinTimestampHeader,
    parseSizeHeader,
} from '../logs-ingestion-consumer'
import type { LogsIngestionMessage } from '../types'
import { LogsPipelineContext, quarantineLogMessage } from './logs-pipeline-context'

export type LogsPipelineInput = { message: Message }

function countDropped(reason: string): void {
    logMessageDroppedCounter.inc({ reason, team_id: 'unknown' })
    recordLogMessageDropped(reason, 'unknown')
}

/**
 * Reads the capture-logs headers and resolves the team. An unknown token, a missing token and a
 * failed team lookup drop the message. Size headers we cannot use and any unexpected failure
 * quarantine it, because those fail the same way on every redelivery.
 */
export function createParseLogsMessageStep<T extends LogsPipelineInput>(
    context: LogsPipelineContext
): ProcessingStep<T, LogsIngestionMessage> {
    const { deps, internalLogsVerifier } = context
    return async function parseLogsMessageStep(input) {
        const message = input.message
        try {
            const headers = parseKafkaHeaders(message.headers)
            const token = headers.token

            if (!token) {
                logger.warn('missing_token')
                countDropped('missing_token')
                return drop('missing_token')
            }

            let team: Team | null
            try {
                if (isDevEnv() && token === 'phc_local') {
                    // phc_local is a special token used in dev to refer to team 1
                    team = await deps.teamManager.getTeam(1)
                } else {
                    team = await deps.teamManager.getTeamByToken(token)
                }
            } catch (e) {
                logger.error('team_lookup_error', { error: e })
                countDropped('team_lookup_error')
                return drop('team_lookup_error')
            }

            if (!team) {
                // A well-formed but unknown or rotated token is a client-input problem, not a
                // service fault. capture-logs accepts any well-formed token shape and defers team
                // resolution to here because it has no Postgres access.
                logger.warn('team_not_found', { token_with_no_team: token })
                countDropped('team_not_found')
                return drop('team_not_found')
            }

            const bytesUncompressed = parseSizeHeader(headers.bytes_uncompressed)
            const bytesUncompressedRecords = parseSizeHeader(headers.bytes_uncompressed_records)
            const bytesCompressed = parseSizeHeader(headers.bytes_compressed)
            const recordCount = parseSizeHeader(headers.record_count)

            if (
                bytesUncompressed === null ||
                bytesUncompressedRecords === null ||
                bytesCompressed === null ||
                recordCount === null
            ) {
                logger.error('🔴', 'logs_ingestion_invalid_size_headers', {
                    teamId: team.id,
                    partition: message.partition,
                    offset: message.offset,
                })
                await quarantineLogMessage(context, message, new Error('invalid_size_headers'), {
                    token,
                    teamId: team.id,
                })
                return drop('invalid_size_headers')
            }

            if (bytesUncompressedRecords > bytesUncompressed) {
                // Billing can only switch from payload-based to records-based bytes if the
                // records sum never exceeds the payload size — flag any violation.
                logsRecordsBytesExceedPayloadCounter.inc({ team_id: team.id.toString() })
            }

            return ok({
                token,
                message,
                teamId: team.id,
                bytesUncompressed,
                bytesUncompressedRecords,
                bytesCompressed,
                recordCount,
                minTimestampMicros: parseMinTimestampHeader(headers.min_timestamp),
                backfillRequested: headers.backfill_days !== undefined,
                internalLogs: internalLogsVerifier.verify(headers[INTERNAL_LOGS_HEADER], team.id, headers.created_at),
            })
        } catch (e) {
            // Includes a failed quarantine of bad size headers: the second attempt below names the
            // DLQ error, and a second failure rejects and fails the batch.
            logger.error('🔴', 'logs_ingestion_parse_error', {
                error: String(e),
                partition: message.partition,
                offset: message.offset,
            })
            countDropped('parse_error')
            await quarantineLogMessage(context, message, e, {})
            return drop('parse_error')
        }
    }
}
