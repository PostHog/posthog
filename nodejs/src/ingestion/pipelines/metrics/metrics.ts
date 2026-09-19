import { Counter } from 'prom-client'

export const metricMessageDroppedCounter = new Counter({
    name: 'metrics_ingestion_message_dropped_count',
    help: 'The number of metrics ingestion messages dropped',
    labelNames: ['reason', 'team_id'],
})

export const metricMessageDlqCounter = new Counter({
    name: 'metrics_ingestion_message_dlq_count',
    help: 'The number of metrics ingestion messages sent to DLQ',
    labelNames: ['reason', 'team_id'],
})

export const metricsBytesReceivedCounter = new Counter({
    name: 'metrics_ingestion_bytes_received_total',
    help: 'Total uncompressed bytes received for metrics ingestion',
})

export const metricsBytesAllowedCounter = new Counter({
    name: 'metrics_ingestion_bytes_allowed_total',
    help: 'Total uncompressed bytes allowed through quota and rate limiting',
})

export const metricsBytesDroppedCounter = new Counter({
    name: 'metrics_ingestion_bytes_dropped_total',
    help: 'Total uncompressed bytes dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const metricsRecordsReceivedCounter = new Counter({
    name: 'metrics_ingestion_records_received_total',
    help: 'Total metric records received',
})

export const metricsRecordsAllowedCounter = new Counter({
    name: 'metrics_ingestion_records_allowed_total',
    help: 'Total metric records allowed through quota and rate limiting',
})

export const metricsRecordsDroppedCounter = new Counter({
    name: 'metrics_ingestion_records_dropped_total',
    help: 'Total metric records dropped due to quota or rate limiting',
    labelNames: ['team_id'],
})

export const metricsPacketsRepackedCounter = new Counter({
    name: 'metrics_ingestion_packets_repacked_total',
    help: 'Input metric packets merged into per-team output packets',
    labelNames: ['team_id'],
})

export const metricsPacketsProducedCounter = new Counter({
    name: 'metrics_ingestion_packets_produced_total',
    help: 'Per-team output metric packets produced to ClickHouse',
    labelNames: ['team_id'],
})
