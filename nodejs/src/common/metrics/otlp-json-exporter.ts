import { Attributes, ValueType } from '@opentelemetry/api'
import {
    AggregationTemporality,
    DataPoint,
    DataPointType,
    Histogram as HistogramValue,
    MetricData,
    PushMetricExporter,
    ResourceMetrics,
} from '@opentelemetry/sdk-metrics'

import { logger } from '~/common/utils/logger'
import { internalFetch } from '~/common/utils/request'

import { BufferedExemplar, drainExemplars, exemplarKey } from './exemplars'

/**
 * OTLP/JSON metrics exporter that serializes exemplars.
 *
 * Exists because the upstream JS pipeline cannot carry exemplars at all:
 * sdk-metrics never samples them and otlp-transformer's data-point transforms
 * drop everything but the core fields, so OTLPMetricExporter physically cannot
 * emit one. The SDK still does all aggregation; this class only replaces the
 * wire encoding, merging in the exemplar side-buffer (see exemplars.ts).
 *
 * Wire shape follows the OTLP/JSON spec that capture-logs parses: camelCase
 * fields, hex-encoded traceId/spanId, unix nanos as decimal strings.
 */

// OTLP proto enum values (AggregationTemporality); the SDK's own enum numbers differ.
const OTLP_TEMPORALITY_DELTA = 1
const OTLP_TEMPORALITY_CUMULATIVE = 2

// Structural stand-in for @opentelemetry/core's ExportResult/ExportResultCode
// (not a direct dependency of this workspace); the values are spec-stable.
interface ExportResult {
    code: number
    error?: Error
}
const EXPORT_SUCCESS = 0
const EXPORT_FAILED = 1

interface OtlpJsonMetricExporterOptions {
    url: string
    headers?: Record<string, string>
}

const hrTimeToNanoString = (hrTime: [number, number]): string =>
    (BigInt(hrTime[0]) * 1_000_000_000n + BigInt(hrTime[1])).toString()

const toAnyValue = (value: unknown): Record<string, unknown> => {
    if (typeof value === 'string') {
        return { stringValue: value }
    }
    if (typeof value === 'boolean') {
        return { boolValue: value }
    }
    if (typeof value === 'number') {
        return Number.isInteger(value) ? { intValue: value } : { doubleValue: value }
    }
    if (Array.isArray(value)) {
        return { arrayValue: { values: value.map(toAnyValue) } }
    }
    return { stringValue: String(value) }
}

const toKeyValueList = (attributes: Attributes): Record<string, unknown>[] =>
    Object.entries(attributes).map(([key, value]) => ({ key, value: toAnyValue(value) }))

const toOtlpTemporality = (temporality: AggregationTemporality): number =>
    temporality === AggregationTemporality.DELTA ? OTLP_TEMPORALITY_DELTA : OTLP_TEMPORALITY_CUMULATIVE

const toExemplarJson = (exemplar: BufferedExemplar): Record<string, unknown> => ({
    filteredAttributes: [],
    timeUnixNano: exemplar.timeUnixNano,
    asDouble: exemplar.value,
    traceId: exemplar.traceId,
    spanId: exemplar.spanId,
})

export class OtlpJsonMetricExporter implements PushMetricExporter {
    constructor(private readonly options: OtlpJsonMetricExporterOptions) {}

    selectAggregationTemporality(): AggregationTemporality {
        return AggregationTemporality.CUMULATIVE
    }

    export(metrics: ResourceMetrics, resultCallback: (result: ExportResult) => void): void {
        const body = JSON.stringify(this.serialize(metrics))
        internalFetch(this.options.url, {
            method: 'POST',
            headers: { ...this.options.headers, 'Content-Type': 'application/json' },
            body,
        })
            .then(async (response) => {
                await response.dump()
                if (response.status >= 200 && response.status < 300) {
                    resultCallback({ code: EXPORT_SUCCESS })
                } else {
                    logger.warn('OTLP JSON metrics export rejected', { status: response.status })
                    resultCallback({ code: EXPORT_FAILED })
                }
            })
            .catch((error) => {
                logger.warn('OTLP JSON metrics export failed', { error: String(error) })
                resultCallback({ code: EXPORT_FAILED, error })
            })
    }

    forceFlush(): Promise<void> {
        return Promise.resolve()
    }

    shutdown(): Promise<void> {
        return Promise.resolve()
    }

    private serialize(metrics: ResourceMetrics): Record<string, unknown> {
        const exemplars = drainExemplars()
        return {
            resourceMetrics: [
                {
                    resource: { attributes: toKeyValueList(metrics.resource.attributes as Attributes) },
                    scopeMetrics: metrics.scopeMetrics.map((scopeMetrics) => ({
                        scope: {
                            name: scopeMetrics.scope.name,
                            ...(scopeMetrics.scope.version ? { version: scopeMetrics.scope.version } : {}),
                        },
                        metrics: scopeMetrics.metrics
                            .map((metricData) => this.serializeMetric(metricData, exemplars))
                            .filter((metric): metric is Record<string, unknown> => metric !== null),
                    })),
                },
            ],
        }
    }

    private serializeMetric(
        metricData: MetricData,
        exemplars: Map<string, BufferedExemplar>
    ): Record<string, unknown> | null {
        const base = {
            name: metricData.descriptor.name,
            description: metricData.descriptor.description,
            unit: metricData.descriptor.unit,
        }
        switch (metricData.dataPointType) {
            case DataPointType.SUM:
                return {
                    ...base,
                    sum: {
                        dataPoints: metricData.dataPoints.map((dp) =>
                            this.serializeNumberDataPoint(dp, metricData, exemplars)
                        ),
                        aggregationTemporality: toOtlpTemporality(metricData.aggregationTemporality),
                        isMonotonic: metricData.isMonotonic,
                    },
                }
            case DataPointType.GAUGE:
                return {
                    ...base,
                    gauge: {
                        dataPoints: metricData.dataPoints.map((dp) =>
                            this.serializeNumberDataPoint(dp, metricData, exemplars)
                        ),
                    },
                }
            case DataPointType.HISTOGRAM:
                return {
                    ...base,
                    histogram: {
                        dataPoints: metricData.dataPoints.map((dp) =>
                            this.serializeHistogramDataPoint(dp, metricData.descriptor.name, exemplars)
                        ),
                        aggregationTemporality: toOtlpTemporality(metricData.aggregationTemporality),
                    },
                }
            default:
                // We create no exponential histograms; dropping beats sending a shape
                // the ingest would reject.
                logger.warn('OTLP JSON metrics export skipping unsupported data point type', {
                    name: metricData.descriptor.name,
                    dataPointType: metricData.dataPointType,
                })
                return null
        }
    }

    private serializeNumberDataPoint(
        dataPoint: DataPoint<number>,
        metricData: MetricData,
        exemplars: Map<string, BufferedExemplar>
    ): Record<string, unknown> {
        const exemplar = exemplars.get(exemplarKey(metricData.descriptor.name, dataPoint.attributes))
        return {
            attributes: toKeyValueList(dataPoint.attributes),
            startTimeUnixNano: hrTimeToNanoString(dataPoint.startTime),
            timeUnixNano: hrTimeToNanoString(dataPoint.endTime),
            ...(metricData.descriptor.valueType === ValueType.INT
                ? { asInt: dataPoint.value }
                : { asDouble: dataPoint.value }),
            ...(exemplar ? { exemplars: [toExemplarJson(exemplar)] } : {}),
        }
    }

    private serializeHistogramDataPoint(
        dataPoint: DataPoint<HistogramValue>,
        metricName: string,
        exemplars: Map<string, BufferedExemplar>
    ): Record<string, unknown> {
        const exemplar = exemplars.get(exemplarKey(metricName, dataPoint.attributes))
        const histogram = dataPoint.value
        return {
            attributes: toKeyValueList(dataPoint.attributes),
            startTimeUnixNano: hrTimeToNanoString(dataPoint.startTime),
            timeUnixNano: hrTimeToNanoString(dataPoint.endTime),
            count: histogram.count,
            sum: histogram.sum,
            bucketCounts: histogram.buckets.counts,
            explicitBounds: histogram.buckets.boundaries,
            ...(histogram.min !== undefined ? { min: histogram.min } : {}),
            ...(histogram.max !== undefined ? { max: histogram.max } : {}),
            ...(exemplar ? { exemplars: [toExemplarJson(exemplar)] } : {}),
        }
    }
}
