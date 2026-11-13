import { mockInternalFetch } from '~/tests/helpers/mocks/request.mock'

import { DateTime } from 'luxon'
import { Pool } from 'pg'

import {
    APP_METRICS_OUTPUT,
    HOG_INVOCATION_RESULTS_OUTPUT,
    LOG_ENTRIES_OUTPUT,
    MESSAGE_ASSETS_OUTPUT,
} from '~/common/outputs'
import { InternalCaptureService } from '~/common/services/internal-capture'
import { parseJSON } from '~/common/utils/json-parse'
import { TeamManager } from '~/common/utils/team-manager'
import { UUIDT } from '~/common/utils/utils'
import { createRecordingIngestionOutputs } from '~/tests/helpers/recording-ingestion-outputs'

import { FixtureHogFlowBuilder } from '../_tests/builders/hogflow.builder'
import { createHogExecutionGlobals } from '../_tests/fixtures'
import { createExampleHogFlowInvocation } from '../_tests/fixtures-hogflows'
import { EMAIL_STATUS_OUTPUT, WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT } from '../outputs/outputs'
import { CyclotronJobInvocationResult } from '../types'
import { createInvocationResult } from '../utils/invocation-utils'
import { CapturedEventsService } from './captured-events/captured-events.service'
import { ConversionWatchersService } from './conversion-watchers/conversion-watchers.service'
import { TRANSACTIONAL_EMAIL_EVENT } from './hogflows/hogflow-sensitivity'
import { InvocationResultsService } from './invocation-results.service'
import { EmailStatusService } from './messaging/email-status.service'
import { MessageAssetsService } from './messaging/message-assets.service'
import { HogFunctionMonitoringService } from './monitoring/hog-function-monitoring.service'
import { HogInvocationResultsService } from './monitoring/hog-invocation-results.service'
import { WarehouseWebhooksService } from './warehouse/warehouse-webhooks.service'

const CYCLOTRON_DATABASE_URL = 'postgres://posthog:posthog@localhost:5432/test_cyclotron_node'

const team = { id: 2, api_token: 'phc_invocation_results_test' }

const failedTransactionalEmailRun = (): CyclotronJobInvocationResult => {
    const hogFlow = new FixtureHogFlowBuilder().withTeamId(team.id).build()
    const invocation = createExampleHogFlowInvocation(hogFlow, {
        event: { ...createHogExecutionGlobals().event, event: TRANSACTIONAL_EMAIL_EVENT },
    })
    const now = DateTime.utc()
    return createInvocationResult(
        invocation,
        {},
        {
            finished: true,
            error: 'Template not found',
            logs: [{ level: 'error', timestamp: now, message: 'Template not found' }],
            capturedPostHogEvents: [
                {
                    team_id: team.id,
                    event: 'workflow event',
                    distinct_id: 'person-1',
                    timestamp: now.toISO()!,
                    properties: {},
                },
            ],
            warehouseWebhookPayloads: [{ team_id: team.id, schema_id: 'schema-1', payload: { id: 1 } }],
            messageAssets: [
                {
                    team_id: team.id,
                    function_kind: 'hog_flow',
                    function_id: hogFlow.id,
                    parent_run_id: invocation.id,
                    invocation_id: invocation.id,
                    action_id: 'action-1',
                    kind: 'email',
                    distinct_id: 'person-1',
                    person_id: 'person_id',
                    recipient: 'person@example.com',
                    subject: 'Hello',
                    status: 'sent',
                    sent_at: '2026-01-02 03:04:05.678000',
                    version: '1',
                    is_deleted: 0,
                    html: '<p>Hello</p>',
                },
            ],
            conversionWatchers: [
                {
                    id: new UUIDT().toString(),
                    team_id: team.id,
                    function_id: hogFlow.id,
                    run_id: invocation.id,
                    parent_run_id: null,
                    distinct_id: 'person-1',
                    person_id: null,
                    flow_version: 1,
                    goal: { events: [] },
                    created_at: now.toJSDate(),
                    expires_at: now.plus({ days: 1 }).toJSDate(),
                },
            ],
        }
    )
}

const realSinks = (): {
    service: InvocationResultsService
    delivered: (runId: string) => Promise<Record<string, unknown[]>>
    cleanup: (runId: string) => Promise<void>
} => {
    const recording = createRecordingIngestionOutputs([
        APP_METRICS_OUTPUT,
        LOG_ENTRIES_OUTPUT,
        HOG_INVOCATION_RESULTS_OUTPUT,
        WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT,
        MESSAGE_ASSETS_OUTPUT,
        EMAIL_STATUS_OUTPUT,
    ])
    const outputs = recording.outputs as any
    const teamManager = {
        getTeam: (teamId: number) => Promise.resolve(teamId === team.id ? team : null),
    } as unknown as TeamManager
    const service = new InvocationResultsService(
        new HogFunctionMonitoringService(outputs),
        new HogInvocationResultsService(outputs, { HOG_INVOCATION_RESULTS_ENABLED: true }),
        new WarehouseWebhooksService(outputs),
        new CapturedEventsService(
            new InternalCaptureService({ CAPTURE_INTERNAL_URL: 'http://capture.example.com/i/v0/e' }),
            teamManager
        ),
        new MessageAssetsService(outputs),
        new ConversionWatchersService(CYCLOTRON_DATABASE_URL),
        new EmailStatusService(outputs, { EMAIL_STATUS_ENABLED: true })
    )
    const pool = new Pool({ connectionString: CYCLOTRON_DATABASE_URL })
    const delivered = async (runId: string): Promise<Record<string, unknown[]>> => {
        const watchers = await pool.query('SELECT run_id FROM conversion_watchers WHERE run_id = $1', [runId])
        return {
            [APP_METRICS_OUTPUT]: recording.produced(APP_METRICS_OUTPUT),
            [LOG_ENTRIES_OUTPUT]: recording.produced(LOG_ENTRIES_OUTPUT),
            [HOG_INVOCATION_RESULTS_OUTPUT]: recording.produced(HOG_INVOCATION_RESULTS_OUTPUT),
            [WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT]: recording.produced(WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT),
            [MESSAGE_ASSETS_OUTPUT]: recording.produced(MESSAGE_ASSETS_OUTPUT),
            [EMAIL_STATUS_OUTPUT]: recording.produced(EMAIL_STATUS_OUTPUT),
            capture: mockInternalFetch.mock.calls.map(([, init]) => parseJSON(String(init?.body))),
            conversion_watchers: watchers.rows,
        }
    }
    const cleanup = async (runId: string): Promise<void> => {
        await service.stop()
        await pool.query('DELETE FROM conversion_watchers WHERE run_id = $1', [runId])
        await pool.end()
    }
    return { service, delivered, cleanup }
}

describe('InvocationResultsService', () => {
    let monitoringService: jest.Mocked<HogFunctionMonitoringService>
    let invocationResultsRowsService: jest.Mocked<HogInvocationResultsService>
    let warehouseWebhooksService: jest.Mocked<WarehouseWebhooksService>
    let capturedEventsService: jest.Mocked<CapturedEventsService>
    let messageAssetsService: jest.Mocked<MessageAssetsService>
    let conversionWatchersService: jest.Mocked<ConversionWatchersService>
    let emailStatusService: jest.Mocked<EmailStatusService>
    let service: InvocationResultsService

    const results = [
        { capturedPostHogEvents: [], warehouseWebhookPayloads: [] },
        { capturedPostHogEvents: [], warehouseWebhookPayloads: [] },
    ] as unknown as CyclotronJobInvocationResult[]

    beforeEach(() => {
        monitoringService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogFunctionMonitoringService>

        invocationResultsRowsService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<HogInvocationResultsService>

        warehouseWebhooksService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<WarehouseWebhooksService>

        capturedEventsService = {
            queueInvocationResults: jest.fn().mockResolvedValue(undefined),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<CapturedEventsService>

        messageAssetsService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<MessageAssetsService>

        conversionWatchersService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<ConversionWatchersService>

        emailStatusService = {
            queueInvocationResults: jest.fn(),
            flush: jest.fn().mockResolvedValue(undefined),
        } as unknown as jest.Mocked<EmailStatusService>

        service = new InvocationResultsService(
            monitoringService,
            invocationResultsRowsService,
            warehouseWebhooksService,
            capturedEventsService,
            messageAssetsService,
            conversionWatchersService,
            emailStatusService
        )
    })

    describe('queueInvocationResults', () => {
        it('delivers nothing through any sink until flush', async () => {
            const { service: realService, delivered, cleanup } = realSinks()
            const run = failedTransactionalEmailRun()

            try {
                await realService.queueInvocationResults([run])

                expect(await delivered(run.invocation.id)).toEqual({
                    [APP_METRICS_OUTPUT]: [],
                    [LOG_ENTRIES_OUTPUT]: [],
                    [HOG_INVOCATION_RESULTS_OUTPUT]: [],
                    [WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT]: [],
                    [MESSAGE_ASSETS_OUTPUT]: [],
                    [EMAIL_STATUS_OUTPUT]: [],
                    capture: [],
                    conversion_watchers: [],
                })
            } finally {
                await cleanup(run.invocation.id)
            }
        })

        it('awaits the captured-events service (which is async)', async () => {
            let resolveCaptured: () => void = () => {}
            capturedEventsService.queueInvocationResults.mockReturnValueOnce(
                new Promise((resolve) => {
                    resolveCaptured = resolve
                })
            )

            const queuePromise = service.queueInvocationResults(results)
            // Give the microtask queue a chance to run the synchronous calls
            await new Promise((r) => setImmediate(r))

            expect(monitoringService.queueInvocationResults).toHaveBeenCalled()
            expect(warehouseWebhooksService.queueInvocationResults).toHaveBeenCalled()
            // queueInvocationResults should not yet be resolved because captured is still pending
            let resolved = false
            void queuePromise.then(() => {
                resolved = true
            })
            await new Promise((r) => setImmediate(r))
            expect(resolved).toBe(false)

            resolveCaptured()
            await queuePromise
        })
    })

    describe('flush', () => {
        it('delivers the queued batch through every sink', async () => {
            const { service: realService, delivered, cleanup } = realSinks()
            const run = failedTransactionalEmailRun()
            const runId = run.invocation.id

            try {
                await realService.queueInvocationResults([run])
                await realService.flush()

                expect(await delivered(runId)).toEqual({
                    [APP_METRICS_OUTPUT]: expect.arrayContaining([
                        expect.objectContaining({ app_source_id: run.invocation.functionId, metric_name: 'failed' }),
                    ]),
                    [LOG_ENTRIES_OUTPUT]: [
                        expect.objectContaining({ instance_id: runId, message: 'Template not found' }),
                    ],
                    [HOG_INVOCATION_RESULTS_OUTPUT]: [
                        expect.objectContaining({ invocation_id: runId, status: 'failed' }),
                    ],
                    [WAREHOUSE_SOURCE_WEBHOOKS_OUTPUT]: [
                        { team_id: team.id, schema_id: 'schema-1', payload: JSON.stringify({ id: 1 }) },
                    ],
                    [MESSAGE_ASSETS_OUTPUT]: [expect.objectContaining({ invocation_id: runId, subject: 'Hello' })],
                    [EMAIL_STATUS_OUTPUT]: [expect.objectContaining({ message_id: runId, status: 'failed' })],
                    capture: [expect.objectContaining({ api_key: team.api_token, event: 'workflow event' })],
                    conversion_watchers: [{ run_id: runId }],
                })
            } finally {
                await cleanup(runId)
            }
        })

        it('flushes all in parallel (all start before any finish)', async () => {
            const order: string[] = []
            const trackOrder = (name: string) =>
                jest.fn().mockImplementation(() => {
                    order.push(`${name}:start`)
                    return Promise.resolve().then(() => {
                        order.push(`${name}:end`)
                    })
                })

            monitoringService.flush = trackOrder('monitoring')
            invocationResultsRowsService.flush = trackOrder('invocationResults')
            warehouseWebhooksService.flush = trackOrder('warehouse')
            capturedEventsService.flush = trackOrder('captured')

            await service.flush()

            // All should have started before any of them finish — proves Promise.all parallelism.
            const lastStart = Math.max(
                order.indexOf('monitoring:start'),
                order.indexOf('invocationResults:start'),
                order.indexOf('warehouse:start'),
                order.indexOf('captured:start')
            )
            const firstEnd = Math.min(
                order.indexOf('monitoring:end'),
                order.indexOf('invocationResults:end'),
                order.indexOf('warehouse:end'),
                order.indexOf('captured:end')
            )
            expect(lastStart).toBeLessThan(firstEnd)
        })
    })

    describe('queueInvocationResultsAndFlush', () => {
        it('queues across all sub-services then flushes all of them', async () => {
            const callOrder: string[] = []
            monitoringService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('monitoring.queue')
            })
            invocationResultsRowsService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('invocationResults.queue')
            })
            warehouseWebhooksService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('warehouse.queue')
            })
            capturedEventsService.queueInvocationResults = jest.fn().mockImplementation(() => {
                callOrder.push('captured.queue')
                return Promise.resolve()
            })
            monitoringService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('monitoring.flush')
                return Promise.resolve()
            })
            invocationResultsRowsService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('invocationResults.flush')
                return Promise.resolve()
            })
            warehouseWebhooksService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('warehouse.flush')
                return Promise.resolve()
            })
            capturedEventsService.flush = jest.fn().mockImplementation(() => {
                callOrder.push('captured.flush')
                return Promise.resolve()
            })

            await service.queueInvocationResultsAndFlush(results)

            // All queue calls must complete before any flush call starts.
            const lastQueueIdx = Math.max(
                callOrder.indexOf('monitoring.queue'),
                callOrder.indexOf('invocationResults.queue'),
                callOrder.indexOf('warehouse.queue'),
                callOrder.indexOf('captured.queue')
            )
            const firstFlushIdx = Math.min(
                callOrder.indexOf('monitoring.flush'),
                callOrder.indexOf('invocationResults.flush'),
                callOrder.indexOf('warehouse.flush'),
                callOrder.indexOf('captured.flush')
            )
            expect(firstFlushIdx).toBeGreaterThan(lastQueueIdx)
        })
    })

    describe('exposed sub-services', () => {
        it('exposes the underlying services as public readonly fields', () => {
            expect(service.monitoringService).toBe(monitoringService)
            expect(service.invocationResultsRowsService).toBe(invocationResultsRowsService)
            expect(service.warehouseWebhooksService).toBe(warehouseWebhooksService)
            expect(service.capturedEventsService).toBe(capturedEventsService)
        })
    })
})
