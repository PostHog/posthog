import { APP_METRICS_OUTPUT, LOG_ENTRIES_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'

import { MetricLogSource, MinimalAppMetric } from '../../types'
import { HogFunctionMonitoringService, MonitoringOutput } from './hog-function-monitoring.service'

describe('HogFunctionMonitoringService', () => {
    let service: HogFunctionMonitoringService
    let queueMessagesMock: jest.Mock<Promise<void>, [any[]]>

    beforeEach(() => {
        queueMessagesMock = jest.fn().mockResolvedValue(undefined)
        const fakeOutput = {
            produce: jest.fn().mockResolvedValue(undefined),
            queueMessages: queueMessagesMock,
            checkHealth: jest.fn().mockResolvedValue(undefined),
            checkTopicExists: jest.fn().mockResolvedValue(undefined),
        } as any
        service = new HogFunctionMonitoringService(
            new IngestionOutputs<MonitoringOutput>({
                [APP_METRICS_OUTPUT]: fakeOutput,
                [LOG_ENTRIES_OUTPUT]: fakeOutput,
            })
        )
    })

    async function flushedRows(): Promise<Record<string, unknown>[]> {
        await service.flush()
        return (queueMessagesMock.mock.calls[0]?.[0] ?? []).map(
            (m: { value: Buffer }) => parseJSON(m.value.toString()) as Record<string, unknown>
        )
    }

    function metric(overrides: Partial<MinimalAppMetric> = {}): MinimalAppMetric {
        return {
            team_id: 1,
            app_source_id: 'flow-1',
            instance_id: 'action-1',
            metric_kind: 'success',
            metric_name: 'succeeded',
            count: 1,
            ...overrides,
        }
    }

    it('mirrors a versioned hog flow metric under hog_flow_version, keyed by version', async () => {
        service.queueAppMetric(metric({ app_source_version: { id: 'flow-1', version: 3 } }), 'hog_flow')

        const rows = await flushedRows()
        expect(rows).toEqual([
            expect.objectContaining({ app_source: 'hog_flow', app_source_id: 'flow-1', instance_id: 'action-1' }),
            expect.objectContaining({
                app_source: 'hog_flow_version',
                app_source_id: 'flow-1/3',
                instance_id: 'action-1',
            }),
        ])
        // The version is a routing hint, not a column — a stray field breaks the app_metrics2 Kafka table.
        expect(rows.every((row) => !('app_source_version' in row))).toBe(true)
    })

    const unmirroredCases: { name: string; source: MetricLogSource; overrides: Partial<MinimalAppMetric> }[] = [
        { name: 'no version', source: 'hog_flow', overrides: {} },
        { name: 'an undefined version', source: 'hog_flow', overrides: { app_source_version: undefined } },
        {
            // A flow loaded without its `version` column: the id is there but the version isn't.
            name: 'a version-less flow',
            source: 'hog_flow',
            overrides: { app_source_version: { id: 'flow-1', version: undefined as unknown as number } },
        },
        {
            name: 'a versioned hog function',
            source: 'hog_function',
            overrides: { app_source_version: { id: 'flow-1', version: 3 } },
        },
    ]

    it.each(unmirroredCases)('writes only the version-agnostic row for $name', async ({ source, overrides }) => {
        service.queueAppMetric(metric(overrides), source)

        const rows = await flushedRows()
        expect(rows).toHaveLength(1)
        expect(rows[0].app_source).toBe(source)
    })

    it('keeps versions apart when the same metric is counted on either side of a publish', async () => {
        service.queueAppMetric(metric({ app_source_version: { id: 'flow-1', version: 2 }, count: 5 }), 'hog_flow')
        service.queueAppMetric(metric({ app_source_version: { id: 'flow-1', version: 3 }, count: 2 }), 'hog_flow')

        const rows = await flushedRows()
        const byId = Object.fromEntries(rows.map((row) => [`${row.app_source}:${row.app_source_id}`, row.count]))
        // The version-agnostic row aggregates both, so per-version reads and total reads agree.
        expect(byId).toEqual({
            'hog_flow:flow-1': 7,
            'hog_flow_version:flow-1/2': 5,
            'hog_flow_version:flow-1/3': 2,
        })
    })
    it('keys the versioned row by the flow, not the batch run its metrics are grouped under', async () => {
        // Batch-triggered runs put the run id in `app_source_id` so per-run views group correctly.
        // Keying the mirror off that would mint a fresh id every run, so a broadcast's versions would
        // never aggregate across its runs and the documented `<flow id>/<version>` read would miss them.
        service.queueAppMetric(
            metric({ app_source_id: 'batch-run-1', app_source_version: { id: 'flow-1', version: 3 } }),
            'hog_flow'
        )
        service.queueAppMetric(
            metric({ app_source_id: 'batch-run-2', app_source_version: { id: 'flow-1', version: 3 } }),
            'hog_flow'
        )

        const rows = await flushedRows()
        expect(rows.filter((row) => row.app_source === 'hog_flow_version')).toEqual([
            expect.objectContaining({ app_source_id: 'flow-1/3', count: 2 }),
        ])
    })
})
