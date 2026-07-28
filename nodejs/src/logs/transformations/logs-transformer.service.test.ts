import { HogFunctionManagerService } from '~/cdp/services/managers/hog-function-manager.service'
import { HogFunctionMonitoringService } from '~/cdp/services/monitoring/hog-function-monitoring.service'
import { HogWatcherService, HogWatcherState } from '~/cdp/services/monitoring/hog-watcher.service'
import { compileHog } from '~/cdp/templates/compiler'
import { HogFunctionType } from '~/cdp/types'

import type { LogRecord } from '../log-record-avro'
import { LogsTransformerConfig, LogsTransformerService, TransformationBatchBudget } from './logs-transformer.service'

jest.setTimeout(30_000)

const TEAM_ID = 7

const createRecord = (overrides: Partial<LogRecord> = {}): LogRecord => ({
    uuid: '0197a3f2-1111-7000-8000-000000000001',
    trace_id: null,
    span_id: null,
    trace_flags: 0,
    timestamp: 1_780_000_000_000_000_000,
    observed_timestamp: 1_780_000_000_000_000_000,
    body: 'user jane@example.com logged in',
    severity_text: 'info',
    severity_number: 9,
    service_name: 'auth-api',
    resource_attributes: {},
    instrumentation_scope: null,
    event_name: null,
    attributes: { user_email: 'jane@example.com' },
    bytes_uncompressed: 120,
    ...overrides,
})

let functionCounter = 0
const createFunction = async (hog: string, overrides: Partial<HogFunctionType> = {}): Promise<HogFunctionType> => {
    functionCounter++
    return {
        id: `00000000-0000-0000-0000-00000000000${functionCounter}`,
        team_id: TEAM_ID,
        name: `Test fn ${functionCounter}`,
        type: 'transformation_log',
        enabled: true,
        deleted: false,
        bytecode: await compileHog(hog),
        inputs: {},
        inputs_schema: [],
        encrypted_inputs: null,
        filters: null,
        mappings: null,
        masking: null,
        template_id: null,
        execution_order: functionCounter,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        ...overrides,
    } as unknown as HogFunctionType
}

describe('LogsTransformerService', () => {
    let service: LogsTransformerService
    let manager: jest.Mocked<Pick<HogFunctionManagerService, 'getHogFunctionsForTeams' | 'getHogFunctionIdsForTeams'>>
    let monitoring: jest.Mocked<Pick<HogFunctionMonitoringService, 'queueAppMetric' | 'queueLogs' | 'flush'>>
    let config: LogsTransformerConfig

    const setFunctions = (functions: HogFunctionType[]) => {
        manager.getHogFunctionsForTeams.mockResolvedValue({ [TEAM_ID]: functions })
        manager.getHogFunctionIdsForTeams.mockResolvedValue({ [TEAM_ID]: functions.map((f) => f.id) })
    }

    const queuedMetrics = () => monitoring.queueAppMetric.mock.calls.map(([metric]) => metric)

    beforeEach(() => {
        functionCounter = 0
        manager = {
            getHogFunctionsForTeams: jest.fn(),
            getHogFunctionIdsForTeams: jest.fn(),
        } as any
        monitoring = {
            queueAppMetric: jest.fn(),
            queueLogs: jest.fn(),
            flush: jest.fn(),
        } as any
        config = {
            siteUrl: 'http://localhost:8010',
            hogTimeoutMs: 10,
            messageBudgetMs: 50,
            batchBudgetMs: 2000,
            maxErrorLogsPerFunctionPerMessage: 3,
            hogWatcherSampleRate: 0,
        }
        service = new LogsTransformerService(manager as any, monitoring as any, config)
    })

    it('does nothing when the team has no transformations', async () => {
        setFunctions([])
        const records = [createRecord()]

        const result = await service.transformRecords(TEAM_ID, records)

        expect(result.recordsDropped).toBe(0)
        expect(records[0].body).toBe('user jane@example.com logged in')
        expect(monitoring.queueAppMetric).not.toHaveBeenCalled()
    })

    it('mutates all records and queues one aggregated success metric', async () => {
        setFunctions([
            await createFunction(`
                let rec := record
                rec.body := replaceAll(rec.body, 'jane@example.com', '[REDACTED]')
                return rec
            `),
        ])
        const records = [createRecord(), createRecord(), createRecord()]

        const result = await service.transformRecords(TEAM_ID, records)

        expect(result.recordsDropped).toBe(0)
        expect(records).toHaveLength(3)
        for (const record of records) {
            expect(record.body).toBe('user [REDACTED] logged in')
        }
        expect(queuedMetrics()).toEqual([
            expect.objectContaining({ metric_name: 'succeeded', count: 3, team_id: TEAM_ID }),
        ])
        expect(monitoring.queueLogs).not.toHaveBeenCalled()
    })

    it('removes dropped records from the array in place', async () => {
        setFunctions([
            await createFunction(`
                if (record.severity_text == 'debug') {
                    return null
                }
                return record
            `),
        ])
        const records = [
            createRecord({ severity_text: 'debug' }),
            createRecord({ severity_text: 'info' }),
            createRecord({ severity_text: 'debug' }),
        ]
        const reference = records

        const result = await service.transformRecords(TEAM_ID, records)

        expect(result.recordsDropped).toBe(2)
        expect(reference).toHaveLength(1)
        expect(reference[0].severity_text).toBe('info')
        expect(result.recordsDroppedByFunctionId.get('00000000-0000-0000-0000-000000000001')).toBe(2)
        expect(queuedMetrics()).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ metric_name: 'dropped', count: 2 }),
                expect.objectContaining({ metric_name: 'succeeded', count: 1 }),
            ])
        )
    })

    it('chains transformations in order, each seeing the previous mutation', async () => {
        setFunctions([
            await createFunction(`
                let rec := record
                rec.attributes.step := 'one'
                return rec
            `),
            await createFunction(`
                let rec := record
                rec.attributes.step := concat(rec.attributes.step, '-two')
                return rec
            `),
        ])
        const records = [createRecord()]

        await service.transformRecords(TEAM_ID, records)

        expect(records[0].attributes!.step).toBe('"one-two"')
    })

    it('fails open: annotates the record, keeps it, queues error logs, and continues', async () => {
        setFunctions([
            await createFunction(`
                print('about to explode')
                throw Error('boom')
            `),
            await createFunction(`
                let rec := record
                rec.attributes.after := 'ran'
                return rec
            `),
        ])
        const records = [createRecord()]

        const result = await service.transformRecords(TEAM_ID, records)

        expect(result.recordsDropped).toBe(0)
        expect(records).toHaveLength(1)
        expect(records[0].attributes!['$transformations_failed']).toContain('Test fn 1')
        expect(records[0].attributes!.after).toBe('"ran"')
        expect(queuedMetrics()).toEqual(
            expect.arrayContaining([
                expect.objectContaining({ metric_name: 'failed', count: 1 }),
                expect.objectContaining({ metric_name: 'succeeded', count: 1 }),
            ])
        )
        const [logEntries] = monitoring.queueLogs.mock.calls[0]
        expect(logEntries.some((entry) => entry.message.includes('about to explode'))).toBe(true)
        expect(logEntries.some((entry) => entry.level === 'error')).toBe(true)
    })

    it('caps captured error logs per function per message', async () => {
        setFunctions([await createFunction(`throw Error('boom')`)])
        const records = Array.from({ length: 10 }, () => createRecord())

        await service.transformRecords(TEAM_ID, records)

        const [logEntries] = monitoring.queueLogs.mock.calls[0]
        const errorEntries = logEntries.filter((entry) => entry.level === 'error')
        expect(errorEntries).toHaveLength(config.maxErrorLogsPerFunctionPerMessage)
        expect(queuedMetrics()).toEqual(
            expect.arrayContaining([expect.objectContaining({ metric_name: 'failed', count: 10 })])
        )
    })

    it('skips all records and annotates them when the message budget is already exhausted', async () => {
        config.messageBudgetMs = 0
        service = new LogsTransformerService(manager as any, monitoring as any, config)
        setFunctions([await createFunction(`return record`)])
        const records = [createRecord(), createRecord()]

        const result = await service.transformRecords(TEAM_ID, records)

        expect(result.recordsDropped).toBe(0)
        expect(records).toHaveLength(2)
        for (const record of records) {
            expect(record.attributes!['$transformations_skipped']).toBe('"budget"')
        }
        expect(queuedMetrics()).toEqual([expect.objectContaining({ metric_name: 'budget_skipped', count: 2 })])
    })

    it('stops transforming once a shared batch budget is exhausted', async () => {
        setFunctions([await createFunction(`return record`)])
        const budget = new TransformationBatchBudget(0)
        const records = [createRecord()]

        await service.transformRecords(TEAM_ID, records, budget)

        expect(records[0].attributes!['$transformations_skipped']).toBe('"budget"')
        expect(queuedMetrics()).toEqual([expect.objectContaining({ metric_name: 'budget_skipped', count: 1 })])
    })

    it('consumes the batch budget across messages', async () => {
        setFunctions([
            await createFunction(`
                let i := 0
                while (i < 100000) {
                    i := i + 1
                }
                return record
            `),
        ])
        const budget = new TransformationBatchBudget(0.0001)

        const firstMessage = [createRecord()]
        await service.transformRecords(TEAM_ID, firstMessage, budget)
        expect(firstMessage[0].attributes!['$transformations_skipped']).toBeUndefined()
        expect(budget.usedMs).toBeGreaterThan(0)

        const secondMessage = [createRecord()]
        await service.transformRecords(TEAM_ID, secondMessage, budget)
        expect(secondMessage[0].attributes!['$transformations_skipped']).toBe('"budget"')
    })

    it('resolves static input templates once and applies them', async () => {
        setFunctions([
            await createFunction(
                `
                let rec := record
                rec.attributes.tag := inputs.tag
                return rec
            `,
                {
                    inputs: {
                        tag: { value: 'static-tag', order: 0 },
                    },
                } as any
            ),
        ])
        const records = [createRecord(), createRecord()]

        await service.transformRecords(TEAM_ID, records)

        expect(records[0].attributes!.tag).toBe('"static-tag"')
        expect(records[1].attributes!.tag).toBe('"static-tag"')
    })

    it('resolves record-referencing input templates per record', async () => {
        setFunctions([
            await createFunction(
                `
                let rec := record
                rec.attributes.svc := inputs.svc
                return rec
            `,
                {
                    inputs: {
                        svc: {
                            value: 'service = {record.service_name}',
                            bytecode: await compileHog(`return f'service = {record.service_name}'`),
                            order: 0,
                        },
                    },
                } as any
            ),
        ])
        const records = [createRecord({ service_name: 'svc-a' }), createRecord({ service_name: 'svc-b' })]

        await service.transformRecords(TEAM_ID, records)

        expect(records[0].attributes!.svc).toBe('"service = svc-a"')
        expect(records[1].attributes!.svc).toBe('"service = svc-b"')
    })

    it('resolves record-referencing encrypted input templates per record, not from cache', async () => {
        setFunctions([
            await createFunction(
                `
                let rec := record
                rec.attributes.svc := inputs.svc
                return rec
            `,
                {
                    inputs: {},
                    encrypted_inputs: {
                        svc: {
                            value: 'service = {record.service_name}',
                            bytecode: await compileHog(`return f'service = {record.service_name}'`),
                            order: 0,
                        },
                    },
                } as any
            ),
        ])
        const records = [createRecord({ service_name: 'svc-a' }), createRecord({ service_name: 'svc-b' })]

        await service.transformRecords(TEAM_ID, records)

        expect(records[0].attributes!.svc).toBe('"service = svc-a"')
        expect(records[1].attributes!.svc).toBe('"service = svc-b"')
    })

    it('treats a failing input template as an invocation failure, not a transformer bug', async () => {
        setFunctions([
            await createFunction(
                `
                let rec := record
                rec.attributes.tag := inputs.tag
                return rec
            `,
                {
                    inputs: {
                        tag: {
                            value: '{record.missing.deeply.nested}',
                            bytecode: await compileHog(`throw Error('template boom')`),
                            order: 0,
                        },
                    },
                } as any
            ),
        ])
        const records = [createRecord()]

        const result = await service.transformRecords(TEAM_ID, records)

        // Fails open: the record survives untransformed, annotated as failed
        expect(result.recordsDropped).toBe(0)
        expect(records).toHaveLength(1)
        expect(records[0].attributes!['$transformations_failed']).toContain('Test fn 1')
        expect(queuedMetrics()).toEqual([expect.objectContaining({ metric_name: 'failed', count: 1 })])
        const queuedLogs = monitoring.queueLogs.mock.calls.flatMap(([logs]) => logs)
        expect(queuedLogs.some((log) => log.level === 'error' && log.message.includes('template boom'))).toBe(true)
    })

    it('redacts encrypted input values from captured logs', async () => {
        setFunctions([
            await createFunction(
                `
                print('the secret is', inputs.apiKey)
                throw Error('boom')
            `,
                {
                    encrypted_inputs: { apiKey: { value: 'super-secret-key', order: 0 } },
                } as any
            ),
        ])
        const records = [createRecord()]

        await service.transformRecords(TEAM_ID, records)

        const [logEntries] = monitoring.queueLogs.mock.calls[0]
        const printed = logEntries.find((entry) => entry.message.includes('the secret is'))
        expect(printed?.message).toContain('***REDACTED***')
        expect(printed?.message).not.toContain('super-secret-key')
    })

    it('teamHasTransformations uses the cheap id lookup', async () => {
        manager.getHogFunctionIdsForTeams.mockResolvedValue({ [TEAM_ID]: ['some-id'] })
        await expect(service.teamHasTransformations(TEAM_ID)).resolves.toBe(true)

        manager.getHogFunctionIdsForTeams.mockResolvedValue({ [TEAM_ID]: [] })
        await expect(service.teamHasTransformations(TEAM_ID)).resolves.toBe(false)
        expect(manager.getHogFunctionsForTeams).not.toHaveBeenCalled()
    })

    it('flush delegates to the monitoring service', async () => {
        await service.flush()
        expect(monitoring.flush).toHaveBeenCalled()
    })

    describe('HogWatcher integration', () => {
        const createMockWatcher = (): jest.Mocked<
            Pick<HogWatcherService, 'getEffectiveStates' | 'observeAggregatedResults'>
        > =>
            ({
                getEffectiveStates: jest.fn().mockResolvedValue({}),
                observeAggregatedResults: jest.fn().mockResolvedValue(undefined),
            }) as any

        const withWatcher = (watcher: any, sampleRate: number): LogsTransformerService =>
            new LogsTransformerService(
                manager as any,
                monitoring as any,
                { ...config, hogWatcherSampleRate: sampleRate },
                watcher
            )

        it('never touches the watcher when the sample rate is 0', async () => {
            const watcher = createMockWatcher()
            service = withWatcher(watcher, 0)
            setFunctions([await createFunction('return record')])

            await service.transformRecords(TEAM_ID, [createRecord()])

            expect(watcher.getEffectiveStates).not.toHaveBeenCalled()
            expect(watcher.observeAggregatedResults).not.toHaveBeenCalled()
        })

        it('reports one aggregated observation per function when sampled', async () => {
            const watcher = createMockWatcher()
            service = withWatcher(watcher, 1)
            const fn = await createFunction('return record')
            setFunctions([fn])

            await service.transformRecords(TEAM_ID, [createRecord(), createRecord()])

            expect(watcher.observeAggregatedResults).toHaveBeenCalledTimes(1)
            const observations = watcher.observeAggregatedResults.mock.calls[0][0]
            expect(observations).toHaveLength(1)
            expect(observations[0].hogFunction.id).toEqual(fn.id)
            expect(observations[0].totalDurationMs).toBeGreaterThanOrEqual(0)
        })

        it('skips functions the watcher has disabled and records a metric', async () => {
            const watcher = createMockWatcher()
            const fn = await createFunction('return null') // would drop every record if it ran
            watcher.getEffectiveStates.mockResolvedValue({ [fn.id]: { state: HogWatcherState.disabled, tokens: 0 } })
            service = withWatcher(watcher, 1)
            setFunctions([fn])

            const records = [createRecord(), createRecord()]
            const { recordsDropped } = await service.transformRecords(TEAM_ID, records)

            expect(recordsDropped).toEqual(0)
            expect(records).toHaveLength(2)
            expect(watcher.observeAggregatedResults).not.toHaveBeenCalled()
            expect(queuedMetrics()).toContainEqual(
                expect.objectContaining({ metric_name: 'disabled_permanently', app_source_id: fn.id, count: 2 })
            )
        })
    })
})
