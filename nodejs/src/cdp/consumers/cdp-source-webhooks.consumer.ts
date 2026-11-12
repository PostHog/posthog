import { DateTime } from 'luxon'

import { HogFlow } from '~/cdp/schema/hogflow'
import type { ModifiedRequest } from '~/common/api/router'
import { instrumented } from '~/common/tracing/tracing-utils'
import { logger } from '~/common/utils/logger'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { UUID, UUIDT } from '~/common/utils/utils'

import { HealthCheckResult, HealthCheckResultOk, PluginsServerConfig } from '../../types'
import { createHogFlowInvocation } from '../services/hogflows/hogflow-executor.service'
import { HOG_FLOW_QUOTA_LIMITED_MESSAGE } from '../services/hogflows/hogflow-quota-limiting'
import { actionIdForLogging } from '../services/hogflows/hogflow-utils'
import { IdempotencyKeys } from '../services/hogflows/idempotency-keys'
import { JobQueue } from '../services/job-queue/job-queue.interface'
import { HogWatcherFunctionState, HogWatcherState, sameWatcherState } from '../services/monitoring/hog-watcher.service'
import {
    CyclotronJobInvocationHogFunction,
    CyclotronJobInvocationResult,
    HogFunctionFilterGlobals,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    LogEntryLevel,
    MinimalAppMetric,
} from '../types'
import { logEntry } from '../utils'
import { dualRead, dualWrite } from '../utils/dual-store'
import { createInvocation, createInvocationResult } from '../utils/invocation-utils'
import { CdpConsumerBase, CdpConsumerBaseDeps } from './cdp-base.consumer'

const DISALLOWED_HEADERS = [
    'x-forwarded-for',
    'x-forwarded-host',
    'x-forwarded-proto',
    'x-forwarded-port',
    'cookie',
    'x-csrftoken',
    'proxy-authorization',
    'referer',
    'forwarded',
    'x-real-ip',
    'true-client-ip',
]

const IDEMPOTENCY_KEY_MAX_LENGTH = 255

const getFirstHeaderValue = (value: string | string[] | undefined): string | undefined => {
    return Array.isArray(value) ? value[0] : value
}

export type HogFunctionWebhookResult = {
    status: number
    body: Record<string, any> | string
    contentType?: string
    isBase64Encoded?: boolean
}

export const getCustomHttpResponse = (
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
): HogFunctionWebhookResult | null => {
    if (typeof result.execResult === 'object' && result.execResult && 'httpResponse' in result.execResult) {
        const httpResponse = result.execResult.httpResponse as Record<string, any>
        return {
            status: 'status' in httpResponse && typeof httpResponse.status === 'number' ? httpResponse.status : 500,
            body: 'body' in httpResponse ? httpResponse.body : '',
            contentType:
                'contentType' in httpResponse && typeof httpResponse.contentType === 'string'
                    ? httpResponse.contentType
                    : undefined,
            isBase64Encoded:
                'isBase64Encoded' in httpResponse && typeof httpResponse.isBase64Encoded === 'boolean'
                    ? httpResponse.isBase64Encoded
                    : undefined,
        }
    }

    return null
}

// Metric names a webhook template may raise from its own code. A template signals one with
// `appMetric`, beside `httpResponse`. This lets a template answer 200 to a delivery it cannot
// process, and still record the failure against the function.
const TEMPLATE_APP_METRIC_NAMES = ['missing_credential'] as const satisfies readonly MinimalAppMetric['metric_name'][]

export const getCustomAppMetricName = (
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
): MinimalAppMetric['metric_name'] | null => {
    if (typeof result.execResult === 'object' && result.execResult && 'appMetric' in result.execResult) {
        const appMetric = result.execResult.appMetric
        if (typeof appMetric === 'string' && (TEMPLATE_APP_METRIC_NAMES as readonly string[]).includes(appMetric)) {
            return appMetric as MinimalAppMetric['metric_name']
        }
    }

    return null
}

type IncomingRequest = NonNullable<HogFunctionInvocationGlobals['request']>

type HogFlowTriggerOutcome = {
    result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>
    queuedInvocationId: string | null
}

export class SourceWebhookError extends Error {
    status: number

    constructor(status: number, message: string) {
        super(message)
        this.name = 'SourceWebhookError'
        this.status = status
    }
}

// A 4xx rejection is the API answering the caller as designed, so it stays out of error tracking.
function isUnexpectedWebhookError(error: unknown): boolean {
    return !(error instanceof SourceWebhookError && error.status < 500)
}

export class CdpSourceWebhooksConsumer extends CdpConsumerBase<PluginsServerConfig> {
    protected name = 'CdpSourceWebhooksConsumer'
    private hogQueue: JobQueue
    private hogflowQueue: JobQueue
    private promiseScheduler: PromiseScheduler

    constructor(
        config: PluginsServerConfig,
        deps: CdpConsumerBaseDeps,
        jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue },
        private idempotencyKeys: IdempotencyKeys = new IdempotencyKeys(null, 'workflow-webhook')
    ) {
        super(config, deps)
        this.promiseScheduler = new PromiseScheduler()
        this.hogQueue = jobQueues.hogQueue
        this.hogflowQueue = jobQueues.hogflowQueue
    }

    public async getWebhook(webhookId: string): Promise<{ hogFlow?: HogFlow; hogFunction: HogFunctionType } | null> {
        if (!UUID.validateString(webhookId, false)) {
            return null
        }

        // Check for hog functions
        const hogFunction = await this.hogFunctionManager.getHogFunction(webhookId)
        if (hogFunction?.type === 'source_webhook' && hogFunction.enabled && !hogFunction.deleted) {
            return { hogFunction }
        }

        if (hogFunction?.type === 'warehouse_source_webhook' && hogFunction.enabled && !hogFunction.deleted) {
            const templateId = hogFunction.template_id ?? 'template-warehouse-source-default'
            const template = await this.hogFunctionTemplateManager.getHogFunctionTemplate(templateId)
            if (template) {
                hogFunction.bytecode = template.bytecode
                return { hogFunction }
            }
        }

        // Otherwise check for hog flows
        const hogFlow = await this.hogFlowManager.getHogFlow(webhookId)
        if (hogFlow?.status === 'active' && hogFlow.trigger?.type === 'manual') {
            // This route takes no credentials, so a manual run goes through Django, which checks the user's access.
            throw new SourceWebhookError(
                403,
                'A manual trigger runs only for a signed-in user. Use the trigger button in PostHog or POST /api/projects/:project_id/hog_flows/:id/run/.'
            )
        }
        if (
            hogFlow &&
            hogFlow.status === 'active' &&
            (hogFlow.trigger?.type === 'webhook' || hogFlow.trigger?.type === 'tracking_pixel')
        ) {
            const hogFunction = await this.hogFlowFunctionsService.buildHogFunction(hogFlow, hogFlow.trigger)

            return { hogFlow, hogFunction }
        }

        return null
    }

    private parseRequest(req: ModifiedRequest): IncomingRequest {
        const ipValue = getFirstHeaderValue(req.headers['x-forwarded-for']) || req.socket.remoteAddress || req.ip
        // IP could be comma delimited list of IPs
        const ips = ipValue?.split(',').map((ip) => ip.trim()) || []
        const ip = ips[0]

        const headers: Record<string, string> = {}

        for (const [key, value] of Object.entries(req.headers)) {
            const firstValue = getFirstHeaderValue(value)
            if (firstValue && !DISALLOWED_HEADERS.includes(key.toLowerCase())) {
                headers[key.toLowerCase()] = firstValue
            }
        }

        const query: Record<string, string> = {}
        for (const [key, value] of Object.entries(req.query)) {
            const firstValue = Array.isArray(value) ? value.join(',') : value
            query[key] = String(firstValue)
        }

        return {
            method: req.method,
            headers,
            ip,
            body: req.body,
            query,
            stringBody: req.rawBody ?? '',
        }
    }

    private buildRequestGlobals(hogFunction: HogFunctionType, request: IncomingRequest): HogFunctionInvocationGlobals {
        const projectUrl = `${this.config.SITE_URL}/project/${hogFunction.team_id}`

        return {
            source: {
                id: hogFunction.id,
                name: hogFunction.name ?? `Hog function: ${hogFunction.id}`,
                url: `${projectUrl}/functions/${hogFunction.id}`,
            },
            project: {
                id: hogFunction.team_id,
                name: '',
                url: '',
            },
            event: {
                event: '$incoming_webhook',
                properties: {},
                uuid: new UUIDT().toString(),
                distinct_id: request.body.distinct_id,
                elements_chain: '',
                timestamp: DateTime.now().toISO(),
                url: '',
            },
            request,
            variables: request.body.$variables || {},
        }
    }

    private getIdempotencyKey(request: IncomingRequest, hogFlow: HogFlow): string | null {
        if (hogFlow.trigger?.type !== 'webhook') {
            return null
        }
        const idempotencyKey = request.headers['idempotency-key']
        if (!idempotencyKey) {
            return null
        }
        if (idempotencyKey.length > IDEMPOTENCY_KEY_MAX_LENGTH) {
            throw new SourceWebhookError(
                400,
                `Idempotency-Key must be ${IDEMPOTENCY_KEY_MAX_LENGTH} characters or fewer`
            )
        }
        return idempotencyKey
    }

    private async executeHogFlow(
        request: IncomingRequest,
        hogFlow: HogFlow,
        hogFunction: HogFunctionType
    ): Promise<HogFlowTriggerOutcome> {
        const idempotencyKey = this.getIdempotencyKey(request, hogFlow)
        // A key belongs to one workflow, so the same key on two workflows starts a run on each.
        const scopedIdempotencyKey = idempotencyKey ? `${hogFlow.id}/${idempotencyKey}` : null

        logger.info('Executing hog flow trigger', {
            id: hogFlow.id,
            template_id: hogFunction.template_id,
            team_id: hogFlow.team_id,
        })
        const invocationId = new UUIDT().toString()
        const triggerActionId = hogFlow.actions.find((action) => action.type === 'trigger')?.id ?? 'trigger_node'

        const addLog = (level: LogEntryLevel, message: string) => {
            this.hogFunctionMonitoringService.queueLogs(
                [
                    {
                        team_id: hogFlow.team_id,
                        log_source: 'hog_flow',
                        log_source_id: hogFlow.id,
                        instance_id: invocationId,
                        ...logEntry(level, `${actionIdForLogging({ id: triggerActionId })} ${message}`),
                    },
                ],
                'hog_flow'
            )
        }

        const addMetric = (metric: Pick<MinimalAppMetric, 'metric_kind' | 'metric_name' | 'count'>) => {
            this.hogFunctionMonitoringService.queueAppMetric(
                {
                    team_id: hogFlow.team_id,
                    app_source_id: hogFlow.id,
                    ...metric,
                },
                'hog_flow'
            )
        }

        try {
            const globals: HogFunctionInvocationGlobals = this.buildRequestGlobals(hogFunction, request)

            const globalsWithInputs = await this.hogExecutorAsync.hogExecutor.buildInputsWithGlobals(
                hogFunction,
                globals
            )
            const invocation = createInvocation(globalsWithInputs, hogFunction)
            let queuedInvocationId: string | null = null

            // Slightly different handling for hog flows
            // Run the initial step - this allows functions not using fetches to respond immediately
            const functionResult = await this.hogFlowFunctionsService.execute(invocation)
            functionResult.logs.forEach((log) => addLog(log.level, log.message))
            functionResult.logs = []

            // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
            if (!functionResult.finished) {
                throw new SourceWebhookError(500, 'Delayed processing not supported')
            }

            const customHttpResponse = getCustomHttpResponse(functionResult)
            if (customHttpResponse) {
                const level = customHttpResponse.status >= 400 ? 'warn' : 'info'
                if (level === 'warn') {
                    const bodyStr =
                        typeof customHttpResponse.body === 'string'
                            ? customHttpResponse.body
                            : JSON.stringify(customHttpResponse.body)
                    addLog(level, `Responded with response status - ${customHttpResponse.status}, reason: ${bodyStr}`)
                } else {
                    addLog(level, `Responded with response status - ${customHttpResponse.status}`)
                }
            }

            const capturedPostHogEvent = functionResult.capturedPostHogEvents[0]
            // Add all logs to the result

            if (capturedPostHogEvent) {
                // For workflows, the captured event is only used as trigger data and not to actually capture the event
                // Remove the execution count property to allow workflow actions to capture events without
                // triggering the infinite loop protection.
                const { $hog_function_execution_count, ...cleanProperties } = capturedPostHogEvent.properties || {}

                // Invoke the hogflow
                const triggerGlobals: HogFunctionInvocationGlobals = {
                    ...invocation.state.globals,
                    event: {
                        ...capturedPostHogEvent,
                        properties: cleanProperties,
                        uuid: new UUIDT().toString(),
                        elements_chain: '',
                        url: '',
                    },
                }
                const hogFlowInvocation = createHogFlowInvocation(
                    triggerGlobals,
                    hogFlow,
                    {} as HogFunctionFilterGlobals
                )

                hogFlowInvocation.id = invocationId // Keep the IDs consistent

                if (scopedIdempotencyKey) {
                    // Every repeat of a key on the workflow is the same request, so the fingerprint is the workflow.
                    const reservation = await this.idempotencyKeys.reserve(
                        hogFlow.team_id,
                        scopedIdempotencyKey,
                        hogFlow.id,
                        invocationId
                    )
                    if (reservation.status === 'replayed') {
                        addLog('info', `Skipped duplicate request for Idempotency-Key "${idempotencyKey}"`)
                        functionResult.finished = false
                        functionResult.execResult = { httpResponse: { status: 200, body: { status: 'duplicate' } } }
                        return { result: functionResult, queuedInvocationId: null }
                    }
                    if (reservation.status === 'in_flight') {
                        // The first request can still fail to queue, so this one must not report a duplicate.
                        functionResult.finished = false
                        functionResult.execResult = { httpResponse: { status: 409, body: { status: 'in_flight' } } }
                        return { result: functionResult, queuedInvocationId: null }
                    }
                    if (reservation.status === 'unavailable') {
                        // A webhook run matters more than its deduplication, so the run queues without a claim.
                        logger.warn('Idempotency store unavailable, queueing the hog flow run anyway', {
                            team_id: hogFlow.team_id,
                            hog_flow_id: hogFlow.id,
                        })
                    }
                }

                const releaseReservation = async (): Promise<void> => {
                    if (scopedIdempotencyKey) {
                        await this.idempotencyKeys.release(hogFlow.team_id, scopedIdempotencyKey, invocationId)
                    }
                }

                const quotaLimited = await this.isHogFlowQuotaLimited(hogFlow).catch(async (error) => {
                    await releaseReservation()
                    throw error
                })
                if (quotaLimited) {
                    await releaseReservation()
                    addLog('warn', `Started no run: ${HOG_FLOW_QUOTA_LIMITED_MESSAGE}`)
                    functionResult.finished = false
                    if (hogFlow.trigger?.type !== 'tracking_pixel') {
                        functionResult.execResult = {
                            httpResponse: { status: 429, body: { error: HOG_FLOW_QUOTA_LIMITED_MESSAGE } },
                        }
                    }
                    return { result: functionResult, queuedInvocationId: null }
                }

                addMetric({
                    metric_kind: 'other',
                    metric_name: 'triggered',
                    count: 1,
                })

                // Queued before queueInvocations serializes the invocation, because
                // queueLifecycleRow stamps `state.firstScheduledAt` and only a stamp set before
                // serialization reaches cyclotron.
                this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(
                    hogFlowInvocation,
                    'running'
                )

                try {
                    await this.hogflowQueue.queueInvocations([hogFlowInvocation])
                } catch (error) {
                    await releaseReservation()
                    throw error
                }
                queuedInvocationId = invocationId
                if (scopedIdempotencyKey) {
                    await this.idempotencyKeys.markQueued(
                        hogFlow.team_id,
                        scopedIdempotencyKey,
                        hogFlow.id,
                        invocationId
                    )
                }
            } else {
                addMetric({
                    metric_kind: 'failure',
                    metric_name: 'trigger_failed',
                    count: 1,
                })
            }
            // Always set to false for hog flows as this triggers the flow to continue so we dont want metrics for this
            functionResult.finished = false

            return { result: functionResult, queuedInvocationId }
        } catch (error) {
            logger.error('Error triggering hog flow', { error })
            // The 'running' row is queued before the invocation reaches cyclotron, so a throw after
            // that point leaves a row for a run that does not exist and would never terminate.
            this.invocationResultsService.invocationResultsRowsService.dropQueuedRowsFor([invocationId])
            addMetric({
                metric_kind: 'failure',
                metric_name: 'trigger_failed',
                count: 1,
            })

            addLog('error', `Error triggering flow: ${error.message}`)

            // NOTE: We only return a hog function result. We track out own logs and errors here
            return {
                result: createInvocationResult(
                    createInvocation({} as any, hogFunction),
                    {},
                    {
                        finished: false,
                        error: error.message,
                    }
                ),
                queuedInvocationId: null,
            }
        }
    }

    private async executeHogFunction(
        req: ModifiedRequest,
        hogFunction: HogFunctionType,
        hogFunctionState: HogWatcherFunctionState | null
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        let result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>

        try {
            const globals: HogFunctionInvocationGlobals = this.buildRequestGlobals(hogFunction, this.parseRequest(req))
            const globalsWithInputs = await this.hogExecutorAsync.hogExecutor.buildInputsWithGlobals(
                hogFunction,
                globals
            )
            const invocation = createInvocation(globalsWithInputs, hogFunction)

            if (hogFunctionState?.state === HogWatcherState.degraded) {
                // Degraded functions are not executed immediately
                invocation.queue = 'hogoverflow'
                await this.hogQueue.queueInvocations([invocation])

                result = createInvocationResult<CyclotronJobInvocationHogFunction>(
                    invocation,
                    {},
                    {
                        finished: false,
                        logs: [
                            {
                                level: 'warn',
                                message: 'Function scheduled for future execution due to degraded state',
                                timestamp: DateTime.now(),
                            },
                        ],
                    }
                )

                result.execResult = {
                    // TODO: Add support for a default response as an input
                    httpResponse: {
                        status: 200,
                        body: '',
                    },
                }
            } else {
                // Run the initial step - this allows functions not using fetches to respond immediately
                result = await this.hogExecutorAsync.execute(invocation)

                // Queue any queued work here. This allows us to enable delayed work like fetching eventually without blocking the API.
                if (!result.finished) {
                    await this.hogQueue.queueInvocationResults([result])
                }

                const customHttpResponse = getCustomHttpResponse(result)
                const customAppMetricName = getCustomAppMetricName(result)

                if (customAppMetricName) {
                    result.metrics.push({
                        team_id: hogFunction.team_id,
                        app_source_id: hogFunction.id,
                        metric_kind: 'failure',
                        metric_name: customAppMetricName,
                        count: 1,
                    })
                }

                if (customHttpResponse) {
                    // A template that drops a delivery answers 200, to stop the provider retrying.
                    // The status alone therefore no longer shows whether we processed the delivery.
                    const level = customHttpResponse.status >= 400 || customAppMetricName ? 'warn' : 'info'
                    if (level === 'warn') {
                        const bodyStr =
                            typeof customHttpResponse.body === 'string'
                                ? customHttpResponse.body
                                : JSON.stringify(customHttpResponse.body)
                        result.logs.push(
                            logEntry(
                                level,
                                `Responded with response status - ${customHttpResponse.status}, reason: ${bodyStr}`
                            )
                        )
                    } else {
                        result.logs.push(
                            logEntry(level, `Responded with response status - ${customHttpResponse.status}`)
                        )
                    }
                }
            }
        } catch (error) {
            logger.error('Error executing hog function', { error })
            result = createInvocationResult(
                createInvocation({} as any, hogFunction),
                {},
                {
                    finished: true,
                    error: error.message,
                    logs: [{ level: 'error', message: error.message, timestamp: DateTime.now() }],
                }
            )
        }

        await this.invocationResultsService.queueInvocationResults([result])
        return result
    }

    @instrumented({
        key: 'cdpSourceWebhooksConsumer.processWebhook',
        shouldCaptureException: isUnexpectedWebhookError,
    })
    public async processWebhook(
        identifier: string,
        req: ModifiedRequest
    ): Promise<CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>> {
        // NOTE: To simplify usage we allow setting a range of extensions for webhooks
        // Currently we just ignore it
        const [webhookId, _extension] = identifier.split('.')

        const [webhook, hogFunctionState] = await Promise.all([
            this.getWebhook(webhookId),
            dualRead(
                'hog-watcher.getCachedEffectiveState',
                () => this.hogWatcher.getCachedEffectiveState(webhookId),
                () => this.hogWatcherMirror.getCachedEffectiveState(webhookId),
                sameWatcherState
            ),
        ])

        if (!webhook) {
            throw new SourceWebhookError(404, 'Not found')
        }

        const { hogFunction, hogFlow } = webhook

        this.rejectIfDisabled(hogFunctionState, hogFunction, hogFlow ? 'hog_flow' : 'hog_function')

        const result = hogFlow
            ? (await this.executeHogFlow(this.parseRequest(req), hogFlow, hogFunction)).result
            : await this.executeHogFunction(req, hogFunction, hogFunctionState)

        this.scheduleAfterRun(result)

        return result
    }

    // The caller must check that the user may edit the workflow: this method trusts `userId`.
    @instrumented({
        key: 'cdpSourceWebhooksConsumer.processManualTrigger',
        shouldCaptureException: isUnexpectedWebhookError,
    })
    public async processManualTrigger(
        teamId: number,
        hogFlowId: string,
        trigger: { userId: string; variables: Record<string, any> }
    ): Promise<string> {
        if (!UUID.validateString(hogFlowId, false)) {
            throw new SourceWebhookError(400, 'Workflow ID must be a UUID')
        }

        const [hogFlow, hogFunctionState] = await Promise.all([
            this.hogFlowManager.getHogFlow(hogFlowId),
            dualRead(
                'hog-watcher.getCachedEffectiveState',
                () => this.hogWatcher.getCachedEffectiveState(hogFlowId),
                () => this.hogWatcherMirror.getCachedEffectiveState(hogFlowId),
                sameWatcherState
            ),
        ])

        if (!hogFlow || hogFlow.team_id !== teamId) {
            throw new SourceWebhookError(404, 'Workflow not found')
        }
        if (hogFlow.trigger?.type !== 'manual') {
            throw new SourceWebhookError(400, 'Workflow trigger must be of type "manual"')
        }
        if (hogFlow.status !== 'active') {
            throw new SourceWebhookError(400, 'Workflow must be active to run')
        }

        const hogFunction = await this.hogFlowFunctionsService.buildHogFunction(hogFlow, hogFlow.trigger)
        this.rejectIfDisabled(hogFunctionState, hogFunction, 'hog_flow')

        // The same body the editor's trigger button posted to the public webhook route, so saved
        // manual triggers that read `request.body.user_id` keep working.
        const body = { user_id: trigger.userId, $variables: trigger.variables }
        const outcome = await this.executeHogFlow(
            {
                method: 'POST',
                headers: { 'content-type': 'application/json' },
                query: {},
                body,
                stringBody: JSON.stringify(body),
            },
            hogFlow,
            hogFunction
        )

        this.scheduleAfterRun(outcome.result)

        if (outcome.queuedInvocationId) {
            return outcome.queuedInvocationId
        }
        // The trigger ran but started no run: its template refused the request, or it failed.
        // A refusal gets 422 so a template's own 401 or 405 is not mistaken for the route's auth check.
        const httpResponse = getCustomHttpResponse(outcome.result)
        if (httpResponse && httpResponse.status >= 400) {
            const body = httpResponse.body
            const reason =
                typeof body === 'string' ? body : typeof body?.error === 'string' ? body.error : JSON.stringify(body)
            throw new SourceWebhookError(422, `The trigger refused the run (${httpResponse.status}): ${reason}`)
        }
        throw new SourceWebhookError(
            outcome.result.error ? 500 : 400,
            'The trigger did not start a run. Check the workflow logs.'
        )
    }

    private rejectIfDisabled(
        hogFunctionState: HogWatcherFunctionState | null,
        hogFunction: HogFunctionType,
        kind: 'hog_flow' | 'hog_function'
    ): void {
        if (hogFunctionState?.state !== HogWatcherState.disabled) {
            return
        }
        this.hogFunctionMonitoringService.queueAppMetric(
            {
                team_id: hogFunction.team_id,
                app_source_id: hogFunction.id,
                metric_kind: 'failure',
                metric_name: 'disabled_permanently',
                count: 1,
            },
            kind
        )
        throw new SourceWebhookError(429, 'Disabled')
    }

    private scheduleAfterRun(result: CyclotronJobInvocationResult<CyclotronJobInvocationHogFunction>): void {
        void this.promiseScheduler.schedule(
            this.invocationResultsService.flush(),
            dualWrite(
                'hog-watcher.observeResultsBuffered',
                () => this.hogWatcher.observeResultsBuffered(result),
                () => this.hogWatcherMirror.observeResultsBuffered(result)
            )
        )
    }

    public override async start(): Promise<void> {
        await super.start()
        // Make sure we are ready to produce to cyclotron first
        await Promise.all([this.hogQueue.startAsProducer(), this.hogflowQueue.startAsProducer()])
    }

    public override async stop(): Promise<void> {
        await Promise.all([this.hogQueue.stopProducer(), this.hogflowQueue.stopProducer()])
        await this.promiseScheduler.waitForAllSettled()
        // IMPORTANT: super always comes last
        await super.stop()
    }

    public isHealthy(): HealthCheckResult {
        // TODO: What should we consider healthy / unhealthy here? kafka?
        return new HealthCheckResultOk()
    }
}
