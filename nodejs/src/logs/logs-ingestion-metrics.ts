import { Counter, Histogram } from 'prom-client'

export const logMessageDroppedCounter = new Counter({
    name: 'logs_ingestion_message_dropped_count',
    help: 'The number of logs ingestion messages dropped',
    labelNames: ['reason', 'team_id'],
})

export const logMessageDlqCounter = new Counter({
    name: 'logs_ingestion_message_dlq_count',
    help: 'The number of logs ingestion messages sent to DLQ',
    labelNames: ['reason', 'team_id'],
})

export const logsBytesReceivedCounter = new Counter({
    name: 'logs_ingestion_bytes_received_total',
    help: 'Total uncompressed bytes received for logs ingestion',
})

export const logsBytesAllowedCounter = new Counter({
    name: 'logs_ingestion_bytes_allowed_total',
    help: 'Total uncompressed bytes allowed through quota and rate limiting. Gross of the drop-rule billing credit: billed bytes_ingested = this − logs_ingestion_billing_bytes_credited_total.',
})

export const logsBytesAllowedRecordsCounter = new Counter({
    name: 'logs_ingestion_bytes_allowed_records_total',
    help: 'Records-based uncompressed bytes (sum of per-record sizes) allowed through quota and rate limiting',
})

export const logsRecordsBytesExceedPayloadCounter = new Counter({
    name: 'logs_ingestion_records_bytes_exceed_payload_total',
    help: 'Batches where the records-based bytes sum exceeded the payload-based bytes_uncompressed header',
    labelNames: ['team_id'],
})

export const logsBytesDroppedCounter = new Counter({
    name: 'logs_ingestion_bytes_dropped_total',
    help: 'Total uncompressed bytes dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const logsRecordsReceivedCounter = new Counter({
    name: 'logs_ingestion_records_received_total',
    help: 'Total log records received',
})

export const logsInternalBytesCounter = new Counter({
    name: 'logs_ingestion_internal_bytes_total',
    help: 'Uncompressed bytes of verified internal logs, which stay out of the received and allowed counters.',
    labelNames: ['team_id'],
})

export const logsInternalRecordsCounter = new Counter({
    name: 'logs_ingestion_internal_records_total',
    help: 'Records of verified internal logs, which stay out of the received and allowed counters.',
    labelNames: ['team_id'],
})

export const logsRecordsAllowedCounter = new Counter({
    name: 'logs_ingestion_records_allowed_total',
    help: 'Total log records allowed through quota and rate limiting. Gross of the drop-rule billing credit: billed records_ingested = this − logs_ingestion_billing_records_credited_total.',
})

export const logsRecordsDroppedCounter = new Counter({
    name: 'logs_ingestion_records_dropped_total',
    help: 'Total log records dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const logsSamplingRecordsDroppedCounter = new Counter({
    name: 'logs_ingestion_sampling_records_dropped_total',
    help: 'Log records dropped by head sampling rules',
    labelNames: ['team_id'],
})

export const logsBytesDroppedByRuleCounter = new Counter({
    name: 'logs_ingestion_bytes_dropped_by_rule_total',
    help: 'Bytes dropped by drop rules, summed from per-row bytes_uncompressed.',
    labelNames: ['team_id'],
})

// --- Billing impact of drop rules (Tier 1) ---
export const logsBillingBytesCreditedCounter = new Counter({
    name: 'logs_ingestion_billing_bytes_credited_total',
    help: 'Uncompressed header bytes credited back to billing for rows removed by drop rules (pro-rated).',
    labelNames: ['team_id'],
})

export const logsBillingRecordsCreditedCounter = new Counter({
    name: 'logs_ingestion_billing_records_credited_total',
    help: 'Records removed by drop rules and credited back to billing.',
    labelNames: ['team_id'],
})

// --- Metric rules (generate metrics from logs) ---
export const logsMetricRulesRecordsMatchedCounter = new Counter({
    name: 'logs_metrics_rules_records_matched_total',
    help: 'Log records that matched a metric rule and fed a generated metric data point.',
    labelNames: ['team_id'],
})

export const logsMetricRulesValueSkippedCounter = new Counter({
    name: 'logs_metrics_rules_value_skipped_total',
    help: 'Records matching a value-attribute metric rule whose value was missing or non-numeric.',
    labelNames: ['team_id'],
})

export const logsMetricRulesSeriesOverflowCounter = new Counter({
    name: 'logs_metrics_rules_series_overflow_total',
    help: 'Matching records dropped because a metric rule exceeded its per-batch label-set cap.',
    labelNames: ['team_id'],
})

export const logsMetricRulesEvalErrorCounter = new Counter({
    name: 'logs_metrics_rules_eval_error_total',
    help: 'Per-record metric-rule filter evaluations that threw; the record was skipped for that rule.',
    labelNames: ['team_id'],
})

// --- Pro-rate accuracy-confidence signals (Tier 2). No team_id label — kept low-cardinality. ---
export const logsBillingProrateDivergenceHistogram = new Histogram({
    name: 'logs_ingestion_billing_prorate_divergence',
    help: 'Per-message |content-weighted − record-weighted credit| / header. High = size-skewed batch = pro-rate less trustworthy.',
    buckets: [0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1],
})

export const logsDropBatchRowsHistogram = new Histogram({
    name: 'logs_ingestion_drop_batch_rows',
    help: 'Rows per batch for messages that had drop-rule drops; small batches carry larger pro-rate error.',
    buckets: [1, 2, 5, 10, 50, 100, 500, 1000, 5000],
})

export const logsDropFractionHistogram = new Histogram({
    name: 'logs_ingestion_drop_fraction',
    help: 'Fraction of a message content dropped by drop rules; extreme fractions carry larger pro-rate error.',
    buckets: [0.1, 0.25, 0.5, 0.75, 0.9, 0.99, 1],
})
