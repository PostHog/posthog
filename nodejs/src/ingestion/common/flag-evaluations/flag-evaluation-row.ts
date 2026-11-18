import { pick } from 'lodash'

import { serializeEvent } from '~/ingestion/common/steps/event-processing/emit-event-step'
import { ProcessedEvent, RawKafkaEvent } from '~/types'

// Never add `flag_key`, `response`, `session_id`, `request_id` or `$group_0..4`.
// The Kafka table does not declare them, and the shard computes them from
// `properties` as DEFAULT columns. A DEFAULT fills only a column the insert
// omits. A sent value is stored even where it contradicts `properties`.
const FLAG_EVALUATION_COLUMNS = [
    'uuid',
    'event',
    'properties',
    'timestamp',
    'team_id',
    'distinct_id',
    'created_at',
    'person_id',
    'person_properties',
    'person_created_at',
    'person_mode',
] as const

/**
 * One row for the kafka_flag_evaluations ClickHouse table (JSONEachRow).
 * Keep in sync with posthog/models/flag_evaluations/sql.py.
 *
 * The table mirrors the events schema, so the row is the events wire format
 * narrowed to selected columns declared by the Kafka engine table. Going
 * through serializeEvent keeps every shared field byte-identical to what the
 * events table receives for the same event, rather than a second hand-rolled
 * mapping that could drift from it.
 */
export type FlagEvaluationRow = Pick<RawKafkaEvent, (typeof FLAG_EVALUATION_COLUMNS)[number]>

export function mapProcessedEventToFlagEvaluationRow(event: ProcessedEvent): FlagEvaluationRow {
    return pick(serializeEvent(event), FLAG_EVALUATION_COLUMNS)
}
