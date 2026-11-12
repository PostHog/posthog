import { DateTime } from 'luxon'
import express from 'ultimate-express'
import { z } from 'zod'

import { ModifiedRequest } from '~/common/api/router'
import type { RedisV2 } from '~/common/redis/redis-v2'
import { logger } from '~/common/utils/logger'
import { UUID, UUIDT, delay } from '~/common/utils/utils'
import { LogRecord } from '~/logs/log-record-avro'
import {
    DEFAULT_LOG_TRANSFORMATION_TIMEOUT_MS,
    buildLogRecordGlobals,
    executeLogTransformation,
    resolveLogTransformationInputs,
} from '~/logs/transformations/hog-log-exec'
import { PluginEvent } from '~/plugin-scaffold'

import {
    HealthCheckResult,
    HealthCheckResultError,
    HealthCheckResultOk,
    PluginServerService,
    PluginsServerConfig,
} from '../types'
import { getAsyncFunctionHandler, getRegisteredAsyncFunctionNames } from './async-function-registry'
import './async-functions'
import { createCdpCoreServices } from './cdp-services'
import { CdpConsumerBaseDeps } from './consumers/cdp-base.consumer'
import {
    CdpSourceWebhooksConsumer,
    HogFunctionWebhookResult,
    SourceWebhookError,
} from './consumers/cdp-source-webhooks.consumer'
import { HogTransformerService, createHogTransformerService } from './hog-transformations/hog-transformer.service'
import { RerunJobManager } from './rerun/rerun-job.manager'
import { RerunRequest } from './rerun/rerun-job.types'
import { HogFlow, HogFlowAction } from './schema/hogflow'
import { BatchExportHogFunctionService, NotFoundError, ParseError } from './services/batch-export-hog-function.service'
import type { CyclotronV2JobProducer } from './services/cyclotron-v2'
import { HogExecutorAsyncService, HogExecutorExecuteAsyncOptions } from './services/hog-executor-async.service'
import { MAX_ASYNC_STEPS } from './services/hog-executor.service'
import { HogInputsService } from './services/hog-inputs.service'
import { counterBatchResolverParked } from './services/hogflows/batch-resolver-resume'
import {
    BatchResolverState,
    HOGFLOW_BATCH_RESOLVE_QUEUE,
    serializeResolverState,
} from './services/hogflows/batch-resolver.types'
import { EmailStep, filesWorkflowShape } from './services/hogflows/files-workflow-shape'
import { HogFlowExecutorService, createHogFlowInvocation } from './services/hogflows/hogflow-executor.service'
import { HogFlowFunctionsService } from './services/hogflows/hogflow-functions.service'
import { HogFlowManagerService } from './services/hogflows/hogflow-manager.service'
import { hogFlowPersonLookup, loadHogFlowPerson } from './services/hogflows/hogflow-person'
import { matchesWaitUntilCondition } from './services/hogflows/hogflow-utils'
import { IdempotencyKeys } from './services/hogflows/idempotency-keys'
import { WorkflowStepResumeSchema } from './services/hogflows/step-resume.service'
import {
    ATTACHMENT_UPLOAD_TOKEN_CLAIMS,
    AcceptedSendRequestSchema,
    CODE_SEND_TOKEN_CLAIMS,
    RescheduleRequestSchema,
    TEMPLATE_SEND_TOKEN_CLAIMS,
    TransactionalEmailOutcome,
    TransactionalEmailRequest,
    TransactionalEmailRequestSchema,
    TransactionalEmailStageTimer,
    TransactionalSendRefusal,
    acceptedSendEmailFields,
    isRecipientFormatIssue,
    transactionalEmailRequestsTotal,
} from './services/hogflows/transactional-email'
import { ScheduledTransactionalSends, TransactionalSends } from './services/hogflows/transactional-sends'
import { InvocationResultsService } from './services/invocation-results.service'
import { JobQueue } from './services/job-queue/job-queue.interface'
import { GroupsManagerService, GroupsMap } from './services/managers/groups-manager.service'
import { HogFunctionManagerService } from './services/managers/hog-function-manager.service'
import { PersonsManagerService } from './services/managers/persons-manager.service'
import { TeamWorkflowsConfigService } from './services/managers/team-workflows-config.service'
import {
    ATTACHMENT_VERIFICATION_DEADLINE_MS,
    AttachmentUploads,
    MessageBodies,
    MessageBodySizing,
    SendRefusal,
    countUploadRequest,
} from './services/messaging/attachment-uploads'
import { EmailStatusService } from './services/messaging/email-status.service'
import { EmailSuppressionService } from './services/messaging/email-suppression.service'
import { EmailTrackingService } from './services/messaging/email-tracking.service'
import { EmailValidationService } from './services/messaging/email-validation.service'
import { utmTagsFor } from './services/messaging/helpers/email-html'
import { sesHtmlMaxBytes } from './services/messaging/helpers/ses-html-max-bytes'
import { EmailTrackingCodeSigner } from './services/messaging/helpers/tracking-code'
import { UTM_VALUE_LIMIT_CHARS, utmValueOverLimit } from './services/messaging/helpers/utm'
import { RecipientTokensService } from './services/messaging/recipient-tokens.service'
import {
    HogWatcherService,
    HogWatcherState,
    sameWatcherState,
    sameWatcherStates,
} from './services/monitoring/hog-watcher.service'
import { NativeDestinationExecutorService } from './services/native-destination-executor.service'
import { SegmentDestinationExecutorService } from './services/segment-destination-executor.service'
import { HOG_FUNCTION_TEMPLATES } from './templates'
import {
    CyclotronJobInvocationHogFlow,
    CyclotronJobInvocationHogFunction,
    CyclotronPerson,
    HogFunctionInvocationGlobals,
    HogFunctionType,
    MinimalLogEntry,
} from './types'
import {
    convertToHogFunctionInvocationGlobals,
    isConvertibleClickHouseEvent,
    isNativeHogFunction,
    isSegmentPluginHogFunction,
    sanitizeLogMessage,
} from './utils'
import { recordRequestOrigins } from './utils/cdp-fetch'
import { deadlineAfter, throwIfDeadlinePassed } from './utils/deadline'
import { dualRead, dualWrite } from './utils/dual-store'
import { isHogLimitError, isHogVMError } from './utils/hog-error-classification'
import { convertToHogFunctionFilterGlobal } from './utils/hog-function-filtering'
import { buildHogFunctionInvocations } from './utils/invocation-utils'
import { PosthogJwtAudience } from './utils/jwt-utils'
import { EMAIL_BODY_TAG_LIMIT, countLiquidTags } from './utils/liquid'
import { ScopedServiceJwt } from './utils/scoped-service-jwt'
import { parseWorkflowStepDispatchKey } from './utils/workflow-step-dispatch-key'

// Allowlist of safe content types for webhook responses to prevent XSS
const SAFE_CONTENT_TYPES = new Set([
    'text/plain',
    'text/csv',
    'application/json',
    'application/octet-stream',
    'application/xml',
    'image/gif',
    'image/png',
    'image/jpeg',
    'image/webp',
])

function sanitizeContentType(contentType: string | undefined, fallback: string): string {
    if (!contentType) {
        return fallback
    }
    const normalized = contentType.toLowerCase().trim().split(';')[0].trim()
    if (SAFE_CONTENT_TYPES.has(normalized)) {
        return normalized
    }
    return fallback
}

// Matches the default email template's `to.email` value: `{{ person.properties.email }}`, whitespace-tolerant.
// Anything else (custom property, computed Liquid, static address) makes the dedupe key diverge from the
// actual send target — see `canDedupeByEmail`.
const DEFAULT_EMAIL_TO_TEMPLATE_RE = /^\s*\{\{\s*person\.properties\.email\s*\}\}\s*$/

// One account assignment filter is spread over these three keys.
const ASSIGNMENT_FILTER_KEYS = ['assignment_status', 'assigned_to_user_ids', 'all_roles_unassigned'] as const

function canDedupeByEmail(hogFlow: { actions?: unknown }): boolean {
    if (!Array.isArray(hogFlow.actions)) {
        return false
    }
    const emailActions = hogFlow.actions.filter((action: any) => action?.type === 'function_email')
    if (emailActions.length === 0) {
        return false
    }
    return emailActions.every((action: any) => {
        const toEmail = action?.config?.inputs?.email?.value?.to?.email
        return typeof toEmail === 'string' && DEFAULT_EMAIL_TO_TEMPLATE_RE.test(toEmail)
    })
}

export type CdpApiConfig = PluginsServerConfig
export type CdpApiDeps = CdpConsumerBaseDeps & {
    /** Holds caller-supplied idempotency keys. Null or unset makes the store report itself unavailable. */
    idempotencyValkey?: RedisV2 | null
}

// Null means the cohort asks to wait but its deadline is unreadable. Queuing it unparked would send to a
// cohort that is still calculating, so the caller rejects it.
function parseRealtimeCohort(value: unknown): BatchResolverState['realtimeCohort'] | null {
    if (typeof value !== 'object' || value === null) {
        return undefined
    }
    const { id, team_id, wait_until } = value as { id?: unknown; team_id?: unknown; wait_until?: unknown }
    if (!Number.isInteger(id) || !Number.isInteger(team_id)) {
        return undefined
    }
    if (wait_until === undefined || wait_until === null) {
        return { id: id as number, teamId: team_id as number }
    }
    const waitUntil = typeof wait_until === 'string' ? new Date(wait_until) : null
    if (!waitUntil || isNaN(waitUntil.getTime())) {
        return null
    }
    return { id: id as number, teamId: team_id as number, waitUntil: waitUntil.toISOString() }
}

const emailRenderLimitExceeded = (emailStep: EmailStep): SendRefusal => ({
    status: 400,
    body: {
        error: 'email_render_limit_exceeded',
        reason: `Rendering the "${emailStep.name}" email step went over a template limit on time or length, so the size of this email with its files could not be checked.`,
        fix: 'Simplify the template of this email step, or send this email without files.',
    },
})

const utmValueTooLong = (emailStep: EmailStep, key: string): SendRefusal => ({
    status: 400,
    body: {
        error: 'utm_value_too_long',
        reason: `The ${key} value of the "${emailStep.name}" email step is longer than ${UTM_VALUE_LIMIT_CHARS} characters, so the size of this email with its files could not be checked.`,
        fix: `Shorten the ${key} value of this email step to ${UTM_VALUE_LIMIT_CHARS} characters or fewer, or send this email without files.`,
    },
})

const emailBodyTooManyTags = (emailStep: EmailStep): SendRefusal => ({
    status: 400,
    body: {
        error: 'email_body_too_many_tags',
        reason: `The "${emailStep.name}" email step has more than ${EMAIL_BODY_TAG_LIMIT} Liquid tags, so the size of this email with its files could not be checked.`,
        fix: `Use ${EMAIL_BODY_TAG_LIMIT} Liquid tags or fewer in this email step, or send this email without files.`,
    },
})

const liquidTagsIn = (value: unknown): number => {
    if (typeof value === 'string') {
        return countLiquidTags(value)
    }
    if (value && typeof value === 'object') {
        return Object.values(value).reduce((total: number, item) => total + liquidTagsIn(item), 0)
    }
    return 0
}

const liquidTagsInStep = (emailStep: EmailStep): number =>
    Object.entries(emailStep.config.inputs).reduce((total: number, [key, input]) => {
        if (input?.templating !== 'liquid') {
            return total
        }
        const rendered =
            key === 'email' && input.value && typeof input.value === 'object'
                ? { ...input.value, design: undefined }
                : input.value
        return total + liquidTagsIn(rendered)
    }, 0)

type WorkerRenderContext = { person: CyclotronPerson | undefined; groups: GroupsMap }

const TRANSACTIONAL_SEND_REFUSAL_STATUS: Record<TransactionalSendRefusal, number> = {
    idempotency_key_in_flight: 409,
    idempotency_key_reused: 422,
    idempotency_unavailable: 503,
    not_sendable: 400,
    sending_suspended: 422,
    sending_paused: 422,
    recipient_suppressed: 422,
    quota_limited: 429,
    recipient_unreachable: 422,
    invalid_scheduled_at: 400,
}

const sendBodies = (invocation: CyclotronJobInvocationHogFlow): MessageBodies => {
    const sendFields = acceptedSendEmailFields(invocation.state.send)
    return {
        bodyBytes: [sendFields.html ?? '', sendFields.text ?? ''].map((body) => Buffer.byteLength(body)),
        subject: sendFields.subject ?? '',
    }
}

export class CdpApi {
    private hogExecutorAsync: HogExecutorAsyncService
    private hogInputsService: HogInputsService
    private nativeDestinationExecutorService: NativeDestinationExecutorService
    private segmentDestinationExecutorService: SegmentDestinationExecutorService

    private hogFunctionManager: HogFunctionManagerService
    private hogFlowManager: HogFlowManagerService

    private hogFlowExecutor: HogFlowExecutorService
    private hogFlowFunctionsService: HogFlowFunctionsService
    private hogWatcher: HogWatcherService
    private hogWatcherMirror: HogWatcherService
    private hogTransformer: HogTransformerService
    private invocationResultsService: InvocationResultsService
    private rerunJobManager: RerunJobManager | null = null
    private cdpSourceWebhooksConsumer: CdpSourceWebhooksConsumer
    private hogQueue: JobQueue
    private hogflowQueue: JobQueue
    private emailTrackingService: EmailTrackingService
    private emailTrackingCodeSigner: EmailTrackingCodeSigner
    private recipientTokensService: RecipientTokensService
    private batchExportHogFunctionService: BatchExportHogFunctionService
    private groupsManager: GroupsManagerService
    private personsManager: PersonsManagerService
    private batchResolverProducer: CyclotronV2JobProducer | null
    // Scoped auth for the reschedule_parked and cancel routes (exempted from the shared
    // internal-secret middleware): Django mints per-call JWTs pinned to a team + workflow,
    // one audience per route. Disabled when the key isn't provisioned — the routes then fail closed.
    private rescheduleJwt: ScopedServiceJwt
    private cancelInvocationsJwt: ScopedServiceJwt
    private cancelBatchJwt: ScopedServiceJwt
    private manualRunJwt: ScopedServiceJwt
    private stepResumeJwt: ScopedServiceJwt
    private transactionalEmailJwt: ScopedServiceJwt
    private manageTransactionalEmailJwt: ScopedServiceJwt
    private transactionalEmailIdempotencyKeys: IdempotencyKeys
    private attachmentUploads: AttachmentUploads
    private emailSuppressionService: EmailSuppressionService
    private emailValidationService: EmailValidationService
    private teamWorkflowsConfigService: TeamWorkflowsConfigService
    private emailStatusService: EmailStatusService
    private resumeBatchJwt: ScopedServiceJwt

    constructor(
        private config: PluginsServerConfig,
        private deps: CdpApiDeps,
        jobQueues: { hogQueue: JobQueue; hogflowQueue: JobQueue },
        batchResolverProducer: CyclotronV2JobProducer | null = null
    ) {
        const services = createCdpCoreServices(config, deps, 'cdp-api-redis')

        this.hogFunctionManager = services.hogFunctionManager
        this.hogFlowManager = services.hogFlowManager
        this.recipientTokensService = services.recipientTokensService
        this.emailSuppressionService = services.emailSuppressionService
        this.emailValidationService = services.emailValidationService
        this.teamWorkflowsConfigService = services.teamWorkflowsConfigService
        this.hogExecutorAsync = services.hogExecutorAsync
        this.hogInputsService = services.hogInputsService
        this.hogFlowExecutor = services.hogFlowExecutor
        this.hogFlowFunctionsService = services.hogFlowFunctionsService
        this.nativeDestinationExecutorService = services.nativeDestinationExecutorService
        this.segmentDestinationExecutorService = services.segmentDestinationExecutorService
        this.hogWatcher = services.hogWatcher
        this.hogWatcherMirror = services.hogWatcherMirror
        this.invocationResultsService = services.invocationResultsService
        this.emailStatusService = services.emailStatusService
        this.personsManager = services.personsManager

        // API-only services. The hog-transformer's monitoring service reuses the same
        // resolved outputs registry as the core CDP services — no separate construction.
        this.hogTransformer = createHogTransformerService(config, {
            ...deps,
            monitoringOutputs: services.outputs,
        })
        this.hogQueue = jobQueues.hogQueue
        this.hogflowQueue = jobQueues.hogflowQueue
        this.cdpSourceWebhooksConsumer = new CdpSourceWebhooksConsumer(
            config,
            deps,
            jobQueues,
            new IdempotencyKeys(deps.idempotencyValkey ?? null, 'workflow-webhook')
        )
        this.emailTrackingCodeSigner = new EmailTrackingCodeSigner(
            config.ENCRYPTION_SALT_KEYS,
            config.CDP_EMAIL_TRACKING_URL
        )
        this.emailTrackingService = services.emailTrackingService
        this.groupsManager = new GroupsManagerService(deps.teamManager, deps.groupRepository)
        this.batchExportHogFunctionService = new BatchExportHogFunctionService(
            config.SITE_URL,
            deps.teamManager,
            this.groupsManager,
            this.hogFunctionManager,
            this.hogExecutorAsync,
            this.hogWatcher,
            this.invocationResultsService,
            this.hogWatcherMirror
        )
        this.batchResolverProducer = batchResolverProducer
        this.rescheduleJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_RESCHEDULE_PARKED,
            config.WORKFLOWS_RESCHEDULE_JWT_SECRET || ''
        )
        this.cancelInvocationsJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_CANCEL_INVOCATIONS,
            config.WORKFLOWS_CANCEL_JWT_SECRET || ''
        )
        this.cancelBatchJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_CANCEL_BATCH,
            config.WORKFLOWS_CANCEL_JWT_SECRET || ''
        )
        // The web tier mints this token as it mints the cancel tokens, so it shares their key on its own audience.
        this.manualRunJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_MANUAL_RUN,
            config.WORKFLOWS_CANCEL_JWT_SECRET || ''
        )
        this.stepResumeJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_STEP_RESUME,
            config.WORKFLOWS_STEP_RESUME_JWT_SECRET || ''
        )
        this.transactionalEmailJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_SEND_TRANSACTIONAL_EMAIL,
            config.WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET || ''
        )
        this.manageTransactionalEmailJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_MANAGE_TRANSACTIONAL_EMAIL,
            config.WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET || ''
        )
        this.transactionalEmailIdempotencyKeys = new IdempotencyKeys(
            deps.idempotencyValkey ?? null,
            'transactional-email'
        )
        this.attachmentUploads = new AttachmentUploads(services.attachmentStore, deps.idempotencyValkey ?? null, {
            teams: config.CDP_EMAIL_ATTACHMENTS_TEAMS,
            maxBytesPerTeamDay: config.CDP_EMAIL_ATTACHMENTS_UPLOAD_MAX_BYTES_PER_TEAM_DAY,
        })
        // The same workers that wake parked steps wake parked batch resolvers, so they share the
        // key. The audience keeps a step-resume token from waking a batch, and the reverse.
        this.resumeBatchJwt = new ScopedServiceJwt(
            PosthogJwtAudience.WORKFLOWS_RESUME_BATCH,
            config.WORKFLOWS_STEP_RESUME_JWT_SECRET || ''
        )
    }

    public get service(): PluginServerService {
        return {
            id: 'cdp-api',
            onShutdown: async () => await this.stop(),
            healthcheck: () => this.isHealthy() ?? new HealthCheckResultError('CDP API is not healthy', {}),
        }
    }

    async start(): Promise<void> {
        // CdpSourceWebhooksConsumer.start() calls startAsProducer on both queues
        await this.cdpSourceWebhooksConsumer.start()

        // Rerun endpoints don't run the work — they just enqueue a wrapper
        // job onto the cyclotron-v2 'rerun' queue. A dedicated consumer
        // (`CdpRerunWorkerConsumer`) deployed as PLUGIN_SERVER_MODE=cdp-rerun-worker
        // pages ClickHouse, rehydrates invocations, and commits progress back
        // to the wrapper job via reschedule(state).
        if (this.config.CYCLOTRON_NODE_DATABASE_URL) {
            this.rerunJobManager = new RerunJobManager({
                dbUrl: this.config.CYCLOTRON_NODE_DATABASE_URL,
                maxCount: this.config.HOG_INVOCATION_RERUN_MAX_COUNT,
                runStartPagingTeams: this.config.CDP_RERUN_RUN_START_PAGING_TEAMS,
            })
            await this.rerunJobManager.connect()
        }
    }

    async stop(): Promise<void> {
        // CdpSourceWebhooksConsumer.stop() calls stopProducer on both queues
        await Promise.all([
            this.cdpSourceWebhooksConsumer.stop(),
            this.batchExportHogFunctionService.stop(),
            this.rerunJobManager?.disconnect() ?? Promise.resolve(),
            this.invocationResultsService.stop(),
        ])
    }

    isHealthy(): HealthCheckResult {
        // NOTE: There isn't really anything to check for here so we are just always healthy
        return new HealthCheckResultOk()
    }

    router(): express.Router {
        const router = express.Router()

        const asyncHandler =
            (fn: (req: ModifiedRequest, res: express.Response) => Promise<void>) =>
            (req: ModifiedRequest, res: express.Response, next: express.NextFunction): Promise<void> =>
                fn(req, res).catch(next)

        // API routes (authentication handled globally by middleware)
        router.post('/api/projects/:team_id/hog_functions/:id/invocations', asyncHandler(this.postFunctionInvocation))
        router.post('/api/projects/:team_id/hog_flows/:id/invocations', asyncHandler(this.postHogflowInvocation))
        router.post(
            '/api/projects/:team_id/hog_flows/:id/scheduled_invocations',
            asyncHandler(this.postHogflowScheduledInvocation)
        )
        router.post(
            '/api/projects/:team_id/hog_flows/:id/manual_invocations',
            asyncHandler(this.postHogFlowManualInvocation)
        )
        router.post(
            '/api/projects/:team_id/hog_flows/:id/batch_invocations/:parent_run_id',
            asyncHandler(this.postHogFlowBatchInvocation)
        )
        router.post(
            '/api/projects/:team_id/hog_functions/:id/rerun',
            asyncHandler(this.postRerunInvocations('hog_function'))
        )
        router.post('/api/projects/:team_id/hog_flows/:id/rerun', asyncHandler(this.postRerunInvocations('hog_flow')))
        router.get('/api/projects/:team_id/hog_flows/:id/in_flight_count', asyncHandler(this.getHogFlowInFlightCount))
        router.post(
            '/api/projects/:team_id/hog_flows/:id/reschedule_parked',
            asyncHandler(this.postHogFlowRescheduleParked)
        )
        router.post(
            '/api/projects/:team_id/hog_flows/:id/invocations/cancel',
            asyncHandler(this.postHogFlowCancelInvocations)
        )
        router.post(
            '/api/projects/:team_id/hog_flows/:id/batch_jobs/:batch_job_id/cancel',
            asyncHandler(this.postHogFlowCancelBatchJob)
        )
        router.post(
            '/api/projects/:team_id/hog_flows/:id/batch_jobs/:batch_job_id/resume',
            asyncHandler(this.postHogFlowResumeBatchJob)
        )
        router.post('/api/projects/:team_id/workflow_steps/resume', asyncHandler(this.postWorkflowStepResume))
        router.post(
            '/api/projects/:team_id/hog_flows/:id/transactional_email',
            asyncHandler(this.postTransactionalEmail(TransactionalEmailRequestSchema, TEMPLATE_SEND_TOKEN_CLAIMS))
        )
        router.post(
            '/api/projects/:team_id/hog_flows/:id/transactional_email/send',
            asyncHandler(this.postTransactionalEmail(AcceptedSendRequestSchema, CODE_SEND_TOKEN_CLAIMS))
        )
        router.post(
            '/api/projects/:team_id/transactional_email/attachments/uploads',
            asyncHandler(this.postAttachmentUploads)
        )
        // `:message_id`, not `:id`: verifyScopedWorkflowJwt matches `:id` against a workflow claim.
        router.post(
            '/api/projects/:team_id/transactional_emails/:message_id/cancel',
            asyncHandler(this.postTransactionalEmailCancel)
        )
        router.post(
            '/api/projects/:team_id/transactional_emails/:message_id/reschedule',
            asyncHandler(this.postTransactionalEmailReschedule)
        )
        router.get('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.getFunctionStatus()))
        router.patch('/api/projects/:team_id/hog_functions/:id/status', asyncHandler(this.patchFunctionStatus()))
        router.get('/api/hog_functions/states', asyncHandler(this.getFunctionStates()))
        router.get('/api/hog_function_templates', this.getHogFunctionTemplates)
        router.post('/api/messaging/generate_preferences_token', asyncHandler(this.generatePreferencesToken()))
        router.get('/api/messaging/validate_preferences_token/:token', asyncHandler(this.validatePreferencesToken()))
        router.post(
            '/api/projects/:team_id/hog_functions/:hog_function_id/batch_export_invocations',
            asyncHandler(this.handleBatchExportHogFunction())
        )

        const publicBodySizeLimit = (req: ModifiedRequest, res: express.Response, next: express.NextFunction): void => {
            if (req.rawBody && req.rawBody.length > 512_000) {
                res.status(413).json({ error: 'Request entity too large' })
                return
            }
            next()
        }

        // Public routes (excluded from authentication by middleware)
        router.post(
            '/public/webhooks/dwh/:webhook_id',
            publicBodySizeLimit,
            asyncHandler(this.handleWarehouseSourceWebhook())
        )
        router.post('/public/webhooks/:webhook_id', publicBodySizeLimit, asyncHandler(this.handleWebhook()))
        router.get('/public/webhooks/:webhook_id', asyncHandler(this.handleWebhook()))
        router.get('/public/m/pixel', asyncHandler(this.getEmailTrackingPixel()))
        router.post('/public/m/ses_webhook', publicBodySizeLimit, express.text(), asyncHandler(this.postSesWebhook()))
        router.get('/public/m/redirect', asyncHandler(this.getEmailTrackingRedirect()))

        return router
    }

    private getHogFunctionTemplates = (req: ModifiedRequest, res: express.Response): void => {
        res.json(HOG_FUNCTION_TEMPLATES)
    }

    private getFunctionStatus =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<void> => {
            const { id } = req.params
            const summary = await dualRead(
                'hog-watcher.getPersistedState',
                () => this.hogWatcher.getPersistedState(id),
                () => this.hogWatcherMirror.getPersistedState(id),
                sameWatcherState
            )

            res.json(summary)
        }

    private patchFunctionStatus =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<void> => {
            const { id } = req.params
            const { state } = req.body

            // Check that state is valid
            if (!Object.values(HogWatcherState).includes(state)) {
                res.status(400).json({ error: 'Invalid state' })
                return
            }

            const summary = await dualRead(
                'hog-watcher.getPersistedState',
                () => this.hogWatcher.getPersistedState(id),
                () => this.hogWatcherMirror.getPersistedState(id),
                sameWatcherState
            )
            const hogFunction = await this.hogFunctionManager.fetchHogFunction(id)

            if (!hogFunction) {
                res.status(404).json({ error: 'Hog function not found' })
                return
            }

            // Only allow patching the status if it is different from the current status

            if (summary.state !== state) {
                await dualWrite(
                    'hog-watcher.forceStateChange',
                    () => this.hogWatcher.forceStateChange(hogFunction, state),
                    () => this.hogWatcherMirror.forceStateChange(hogFunction, state)
                )
            }

            // Hacky - wait for a little to give a chance for the state to change
            await delay(100)

            res.json(
                await dualRead(
                    'hog-watcher.getPersistedState',
                    () => this.hogWatcher.getPersistedState(id),
                    () => this.hogWatcherMirror.getPersistedState(id),
                    sameWatcherState
                )
            )
        }

    private getFunctionStates =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<void> => {
            try {
                const allStates = await dualRead(
                    'hog-watcher.getAllFunctionStates',
                    () => this.hogWatcher.getAllFunctionStates(),
                    () => this.hogWatcherMirror.getAllFunctionStates(),
                    sameWatcherStates
                )

                // Transform the data for better consumption by Grafana and sort by tokens ascending
                const statesArray = Object.entries(allStates)
                    .map(([functionId, state]) => ({
                        function_id: functionId,
                        state: HogWatcherState[state.state], // Convert numeric state to readable string
                        tokens: state.tokens,
                        state_numeric: state.state,
                    }))
                    .sort((a, b) => b.state_numeric - a.state_numeric)

                const hogFunctions = await this.hogFunctionManager.getHogFunctions(
                    statesArray.map((x) => x.function_id)
                )

                const results = statesArray.map((x) => ({
                    ...x,
                    function_name: hogFunctions[x.function_id]?.name,
                    function_team_id: hogFunctions[x.function_id]?.team_id,
                    function_type: hogFunctions[x.function_id]?.type,
                    function_enabled: hogFunctions[x.function_id]?.enabled && !hogFunctions[x.function_id]?.deleted,
                }))

                res.json({
                    results,
                    total: results.length,
                })
            } catch (error) {
                logger.error('[CdpApi] Error getting all function states', error)
                res.status(500).json({ error: 'Failed to get function states' })
            }
        }

    private postFunctionInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        const requestOrigins = new Set<string>()
        try {
            const { id, team_id } = req.params
            const { clickhouse_event, mock_async_functions, configuration, invocation_id } = req.body
            let { globals } = req.body

            // Redact configuration: it carries function inputs (auth headers, API keys) that must not land in logs
            logger.info('⚡️', 'Received invocation', {
                id,
                team_id,
                body: { ...req.body, configuration: configuration ? '[redacted]' : undefined },
            })

            const invocationID = invocation_id ?? new UUIDT().toString()

            // Check the invocationId is a valid UUID
            if (!UUID.validateString(invocationID)) {
                res.status(400).json({ error: 'Invalid invocation ID' })
                return
            }

            const isNewFunction = req.params.id === 'new'

            const hogFunction = isNewFunction
                ? null
                : await this.hogFunctionManager.fetchHogFunction(req.params.id).catch(() => null)
            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            globals = isConvertibleClickHouseEvent(clickhouse_event)
                ? convertToHogFunctionInvocationGlobals(clickhouse_event, team, this.config.SITE_URL)
                : globals

            const functionType: string | undefined = configuration?.type ?? hogFunction?.type

            if (functionType === 'transformation_log') {
                // Log transformations run against a log record, not an event
                if (!globals?.record || typeof globals.record !== 'object' || Array.isArray(globals.record)) {
                    res.status(400).json({ error: 'Missing record' })
                    return
                }
            } else if (!globals || !globals.event) {
                res.status(400).json({ error: 'Missing event' })
                return
            }

            // NOTE: We allow the hog function to be null if it is a "new" hog function
            // The real security happens at the django layer so this is more of a sanity check
            if (!isNewFunction && (!hogFunction || hogFunction.team_id !== team.id)) {
                return res.status(404).json({ error: 'Hog function not found' })
            }

            // We use the provided config if given, otherwise the function's config
            const compoundConfiguration: HogFunctionType = {
                ...hogFunction,
                ...configuration,
                team_id: team.id,
            }

            let logs: MinimalLogEntry[] = []
            let result: any = null
            const errors: any[] = []

            const triggerGlobals: HogFunctionInvocationGlobals = {
                ...globals,
                // Sample globals from the app can carry a placeholder project, and a test send with
                // mock_async_functions off delivers for real, so the server's project always wins.
                project: {
                    ...globals.project,
                    id: team.id,
                    name: team.name,
                    url: `${this.config.SITE_URL}/project/${team.id}`,
                },
            }

            if (['destination', 'internal_destination'].includes(compoundConfiguration.type)) {
                const {
                    invocations,
                    logs: filterLogs,
                    metrics: filterMetrics,
                } = await buildHogFunctionInvocations(this.hogInputsService, [compoundConfiguration], triggerGlobals)

                // Add metrics to the logs
                filterMetrics.forEach((metric) => {
                    if (metric.metric_name === 'filtered') {
                        logs.push({
                            level: 'info',
                            timestamp: DateTime.now(),
                            message: `Mapping trigger not matching filters was ignored.`,
                        })
                    }
                })

                filterLogs.forEach((log) => {
                    logs.push(log)
                })

                for (const invocation of invocations) {
                    invocation.id = invocationID

                    const sensitiveValues = this.hogExecutorAsync.hogExecutor.getSensitiveValues(
                        invocation.hogFunction,
                        invocation.state.globals.inputs ?? {}
                    )
                    const options: HogExecutorExecuteAsyncOptions = buildHogExecutorAsyncOptions(
                        mock_async_functions,
                        logs,
                        sensitiveValues
                    )
                    options.isTest = true

                    const response: any = await recordRequestOrigins(requestOrigins, () => {
                        if (isNativeHogFunction(compoundConfiguration)) {
                            return this.nativeDestinationExecutorService.execute(invocation)
                        } else if (isSegmentPluginHogFunction(compoundConfiguration)) {
                            return this.segmentDestinationExecutorService.execute(invocation)
                        }
                        return this.hogExecutorAsync.executeWithAsyncFunctions(invocation, options)
                    })

                    logs = logs.concat(response.logs)
                    if (response.error) {
                        errors.push(response.error)
                    }
                }

                const wasSkipped = invocations.length === 0

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                    request_origins: [...requestOrigins].sort(),
                })
            } else if (compoundConfiguration.type === 'transformation') {
                // NOTE: We override the ID so that the transformer doesn't cache the result
                // TODO: We could do this with a "special" ID to indicate no caching...
                compoundConfiguration.id = new UUIDT().toString()
                const pluginEvent: PluginEvent = {
                    ...triggerGlobals.event,
                    ip:
                        typeof triggerGlobals.event.properties.$ip === 'string'
                            ? triggerGlobals.event.properties.$ip
                            : null,
                    site_url: triggerGlobals.project.url,
                    team_id: triggerGlobals.project.id,
                    now: '',
                }
                const response = await recordRequestOrigins(requestOrigins, () =>
                    this.hogTransformer.transformEvent(pluginEvent, [compoundConfiguration])
                )

                result = response.event

                for (const invocationResult of response.invocationResults) {
                    logs = logs.concat(invocationResult.logs)
                    if (invocationResult.error) {
                        errors.push(invocationResult.error)
                    }
                }

                const wasSkipped = response.invocationResults.some((r) =>
                    r.metrics.some((m) => m.metric_name === 'filtered')
                )

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : wasSkipped ? 'skipped' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                    request_origins: [...requestOrigins].sort(),
                })
            } else if (compoundConfiguration.type === 'transformation_log') {
                const mock = globals.record as Record<string, unknown>

                const toStringMap = (value: unknown): Record<string, string> => {
                    const map: Record<string, string> = {}
                    if (value && typeof value === 'object' && !Array.isArray(value)) {
                        for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
                            if (entry !== null && entry !== undefined) {
                                map[key] = typeof entry === 'string' ? entry : JSON.stringify(entry)
                            }
                        }
                    }
                    return map
                }

                // Mock log record from the request; trace/span ids stay null (they are
                // read-only in transformations and not meaningful for a test run).
                const record: LogRecord = {
                    uuid: invocationID,
                    trace_id: null,
                    span_id: null,
                    trace_flags: null,
                    timestamp: typeof mock.timestamp === 'number' ? mock.timestamp : DateTime.now().toMillis() * 1e6,
                    observed_timestamp: typeof mock.observed_timestamp === 'number' ? mock.observed_timestamp : null,
                    body: typeof mock.body === 'string' ? mock.body : null,
                    severity_text: typeof mock.severity_text === 'string' ? mock.severity_text : null,
                    severity_number: typeof mock.severity_number === 'number' ? mock.severity_number : null,
                    service_name: typeof mock.service_name === 'string' ? mock.service_name : null,
                    resource_attributes: toStringMap(mock.resource_attributes),
                    instrumentation_scope:
                        typeof mock.instrumentation_scope === 'string' ? mock.instrumentation_scope : null,
                    event_name: typeof mock.event_name === 'string' ? mock.event_name : null,
                    attributes: toStringMap(mock.attributes),
                    bytes_uncompressed: null,
                }

                const hogGlobals = buildLogRecordGlobals(record, triggerGlobals.project, {})

                try {
                    hogGlobals.inputs = resolveLogTransformationInputs(
                        compoundConfiguration,
                        hogGlobals,
                        DEFAULT_LOG_TRANSFORMATION_TIMEOUT_MS
                    ).inputs
                } catch (e) {
                    return res.json({
                        result: null,
                        status: 'error',
                        errors: [String(e)],
                        logs,
                        request_origins: [...requestOrigins].sort(),
                    })
                }

                // Derive from the resolved inputs (which merge inputs + encrypted_inputs) like the
                // destination test path does — Django resolves stored secrets into `inputs`, so
                // collecting from `encrypted_inputs` alone would leave them unredacted in test logs.
                const sensitiveValues = this.hogExecutorAsync.hogExecutor.getSensitiveValues(
                    compoundConfiguration,
                    (hogGlobals.inputs ?? {}) as Record<string, any>
                )

                const outcome = executeLogTransformation(compoundConfiguration.bytecode, record, hogGlobals, {
                    sensitiveValues,
                })

                logs = logs.concat(
                    outcome.logs.map((message) => ({
                        level: 'info' as const,
                        timestamp: DateTime.now(),
                        message,
                    }))
                )

                if (outcome.status === 'failed') {
                    errors.push(outcome.error)
                } else if (outcome.status === 'dropped') {
                    logs.push({
                        level: 'info',
                        timestamp: DateTime.now(),
                        message: 'Record dropped by transformation.',
                    })
                }

                // Same record shape the function saw (hex ids, string maps) — null when dropped
                result =
                    outcome.status === 'dropped'
                        ? null
                        : buildLogRecordGlobals(record, triggerGlobals.project, {}).record

                res.json({
                    result: result,
                    status: errors.length > 0 ? 'error' : 'success',
                    errors: errors.map((e) => String(e)),
                    logs: logs,
                    request_origins: [...requestOrigins].sort(),
                })
            } else {
                return res.status(400).json({ error: 'Invalid function type' })
            }
        } catch (e) {
            console.error(e)
            res.status(500).json({ errors: [e.message], request_origins: [...requestOrigins].sort() })
        } finally {
            await this.invocationResultsService.flush()
        }
    }

    private postHogflowInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        const requestOrigins = new Set<string>()
        try {
            const { id, team_id } = req.params
            const { clickhouse_event, configuration, invocation_id, current_action_id, mock_async_functions } = req.body

            // Redact configuration: it carries action inputs (auth headers, API keys) that must not land in logs
            logger.info('⚡️', 'Received hogflow invocation', {
                id,
                team_id,
                body: { ...req.body, configuration: configuration ? '[redacted]' : undefined },
            })

            const invocationID = invocation_id ?? new UUIDT().toString()

            // Check the invocationId is a valid UUID
            if (!UUID.validateString(invocationID)) {
                res.status(400).json({ error: 'Invalid invocation ID' })
                return
            }

            const isNewHogFlow = req.params.id === 'new'
            const hogFlow = isNewHogFlow ? null : await this.hogFlowManager.getHogFlow(req.params.id)

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            // NOTE: We allow the hog flow to be null if it is a "new" hog flow
            // The real security happens at the django layer so this is more of a sanity check
            if (!isNewHogFlow && (!hogFlow || hogFlow.team_id !== team.id)) {
                return res.status(404).json({ error: 'Hog flow not found' })
            }

            const globals: HogFunctionInvocationGlobals | null = isConvertibleClickHouseEvent(clickhouse_event)
                ? convertToHogFunctionInvocationGlobals(
                      clickhouse_event,
                      team,
                      this.config.SITE_URL ?? 'http://localhost:8000'
                  )
                : req.body.globals

            if (!globals || !globals.event) {
                return res.status(400).json({ error: 'Missing event' })
            }

            // We use the provided config if given, otherwise the flow's config
            const compoundConfiguration = {
                ...hogFlow,
                ...configuration,
                team_id: team.id,
            }

            // Mirror real execution: resolve groups server-side from the event's $groups so test-run
            // conditionals branch on group properties. Only resolve when the caller didn't supply
            // groups, so hand-edited test payloads are respected.
            if (!globals.groups || Object.keys(globals.groups).length === 0) {
                globals.groups = await this.groupsManager.getGroupsForEvent(
                    team.id,
                    globals.event.properties,
                    `${this.config.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`
                )
            }

            const triggerGlobals: HogFunctionInvocationGlobals = {
                ...globals,
                project: {
                    id: team.id,
                    name: team.name,
                    url: `${this.config.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
                },
            }

            const filterGlobals = convertToHogFunctionFilterGlobal({
                event: globals.event,
                person: globals.person,
                groups: globals.groups,
                variables: globals.variables || {},
            })

            const invocation = createHogFlowInvocation(triggerGlobals, compoundConfiguration, filterGlobals)

            // Real event ingestion evaluates trigger filters before creating an invocation. A test run has to
            // execute the trigger action itself so callers can verify whether their supplied globals match.
            // Without this explicit position, executeCurrentAction starts after the trigger by design.
            const startingActionId =
                current_action_id ??
                compoundConfiguration.actions?.find((action: HogFlowAction) => action.type === 'trigger')?.id
            invocation.state.currentAction = startingActionId
                ? {
                      id: startingActionId,
                      startedAtTimestamp: Date.now(),
                  }
                : undefined

            const logs: MinimalLogEntry[] = []

            // In production a wait_until_condition step's "events to wait for" are evaluated by the
            // subscription matcher against incoming events (never by the executor), so a plain
            // executeCurrentAction could not advance past one. Simulate the matcher here: when the
            // supplied test event matches, tag the invocation the same way a real match would, and
            // the handler advances to the next step.
            const currentAction: HogFlowAction | undefined = current_action_id
                ? compoundConfiguration.actions?.find((a: HogFlowAction) => a.id === current_action_id)
                : undefined
            if (currentAction?.type === 'wait_until_condition' && invocation.state.currentAction) {
                const matched = await matchesWaitUntilCondition(currentAction, filterGlobals, {
                    hogFlowId: isNewHogFlow ? 'new' : id,
                    actionId: currentAction.id,
                })
                if (matched) {
                    invocation.state.currentAction.eventMatched = true
                    invocation.state.currentAction.eventMatchedEvent = globals.event.event
                    invocation.state.currentAction.eventMatchedEventUuid = globals.event.uuid
                    invocation.state.currentAction.eventMatchedEventTimestamp = globals.event.timestamp
                }
                logs.push({
                    level: 'info',
                    timestamp: DateTime.now(),
                    message: matched
                        ? `Test event '${globals.event.event}' matched the wait conditions`
                        : `Test event '${globals.event.event}' did not match the wait conditions - the workflow would continue waiting`,
                })
            }

            // Redact the flow's decrypted secret inputs from the mocked async-function logs, so a test
            // run can't echo a stored credential (e.g. an Authorization header) back to the caller.
            const sensitiveValues = await this.hogFlowExecutor.getSensitiveValues(compoundConfiguration)
            const options: HogExecutorExecuteAsyncOptions = buildHogExecutorAsyncOptions(
                mock_async_functions,
                logs,
                sensitiveValues
            )
            options.isTest = true
            const result = await recordRequestOrigins(requestOrigins, () =>
                this.hogFlowExecutor.executeCurrentAction(invocation, { hogExecutorOptions: options })
            )

            res.json({
                nextActionId: result.skipped ? null : result.invocation.state.currentAction?.id,
                status: result.error ? 'error' : result.skipped ? 'skipped' : 'success',
                errors: result.error ? [result.error] : [],
                logs: [...result.logs, ...logs],
                variables: result.invocation.state.variables ?? {},
                execResult: result.execResult ?? null,
                ...(result.emailSendResult ? { emailSendResult: result.emailSendResult } : {}),
                request_origins: [...requestOrigins].sort(),
            })
        } catch (e) {
            console.error(e)
            res.status(500).json({ error: [e.message], request_origins: [...requestOrigins].sort() })
        }
    }

    private postHogflowScheduledInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            const { id, team_id } = req.params
            const { variables } = req.body

            logger.info('⚡️', 'Received hogflow scheduled invocation', { id, team_id })

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            const hogFlow = await this.hogFlowManager.getHogFlow(id)
            if (!hogFlow || hogFlow.team_id !== team.id) {
                return res.status(404).json({ error: 'Workflow not found' })
            }

            if (hogFlow.trigger?.type !== 'schedule') {
                return res.status(400).json({ error: 'Workflow trigger must be of type "schedule"' })
            }

            // Build a synthetic event for the scheduled run. Schedule triggers don't have a real
            // event, but the executor expects one to populate globals.event used by downstream actions.
            const syntheticEvent: HogFunctionInvocationGlobals['event'] = {
                uuid: new UUIDT().toString(),
                event: '$workflow_scheduled',
                distinct_id: `workflow-${hogFlow.id}`,
                timestamp: DateTime.now().toISO(),
                url: '',
                properties: {},
                elements_chain: '',
            }

            const triggerGlobals: HogFunctionInvocationGlobals = {
                event: syntheticEvent,
                project: {
                    id: team.id,
                    name: team.name,
                    url: `${this.config.SITE_URL ?? 'http://localhost:8000'}/project/${team.id}`,
                },
                variables: variables ?? {},
            }

            const filterGlobals = convertToHogFunctionFilterGlobal({
                event: syntheticEvent,
                person: undefined,
                groups: {},
                variables: variables ?? {},
            })

            const invocation = createHogFlowInvocation(triggerGlobals, hogFlow, filterGlobals)

            // Queued before queueInvocations serializes the invocation, so the
            // `state.firstScheduledAt` stamp reaches cyclotron.
            this.invocationResultsService.invocationResultsRowsService.queueLifecycleRow(invocation, 'running')

            try {
                await this.hogflowQueue.queueInvocations([invocation])
            } catch (error) {
                this.invocationResultsService.invocationResultsRowsService.dropQueuedRowsFor([invocation.id])
                throw error
            }
            // Only the lifecycle sink, which swallows its own produce failures. Flushing every sink
            // would fail an enqueued run on an unrelated sink's error, and the caller would retry it.
            await this.invocationResultsService.invocationResultsRowsService.flush()

            res.json({ status: 'queued', invocation_id: invocation.id })
        } catch (e) {
            logger.error('Error handling hogflow scheduled invocation', { error: e })
            res.status(500).json({ error: [e.message] })
        }
    }

    // Auth: a per-call JWT that Django mints for this team, workflow and user after it checks that
    // the user may edit the workflow. The route is exempt from the internal API secret.
    private postHogFlowManualInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        if (!this.manualRunJwt.enabled) {
            return res.status(503).json({
                error: 'Workflows scoped auth not configured (WORKFLOWS_CANCEL_JWT_SECRET unset)',
            })
        }
        if (!this.verifyScopedWorkflowJwt(this.manualRunJwt, req, res, 'manual run', { user_id: req.body?.user_id })) {
            return
        }

        const { id, team_id } = req.params
        const parsed = z
            .object({
                user_id: z.string({ error: 'user_id is required' }).min(1, 'user_id is required'),
                variables: z.record(z.string(), z.unknown(), { error: 'variables must be an object' }).optional(),
            })
            .safeParse(req.body ?? {})
        if (!parsed.success) {
            return res.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Invalid request body' })
        }
        const { user_id: userId, variables } = parsed.data

        try {
            const invocationId = await this.cdpSourceWebhooksConsumer.processManualTrigger(parseInt(team_id), id, {
                userId,
                variables: variables ?? {},
            })
            return res.json({ status: 'queued', invocation_id: invocationId })
        } catch (error) {
            if (error instanceof SourceWebhookError) {
                return res.status(error.status).json({ error: error.message })
            }
            logger.error('Error handling hogflow manual invocation', { error })
            return res.status(500).json({ error: 'Internal error' })
        }
    }

    // Rerun endpoints don't run the work — they just enqueue a wrapper job
    // onto the cyclotron-v2 'rerun' queue. The dedicated `CdpRerunWorkerConsumer`
    // picks it up, pages ClickHouse, rehydrates invocations onto the regular
    // queue, and commits progress back to the wrapper job's state.
    private postRerunInvocations =
        (functionKind: 'hog_function' | 'hog_flow') =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            try {
                if (!this.rerunJobManager) {
                    return res.status(503).json({
                        error: 'Rerun manager not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                    })
                }

                const { team_id, id } = req.params
                const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
                if (!team) {
                    return res.status(404).json({ error: 'Team not found' })
                }

                if (functionKind === 'hog_function') {
                    const hogFunction = await this.hogFunctionManager.getHogFunction(id)
                    if (!hogFunction || hogFunction.team_id !== team.id) {
                        return res.status(404).json({ error: 'Hog function not found' })
                    }
                } else {
                    const hogFlow = await this.hogFlowManager.getHogFlow(id)
                    if (!hogFlow || hogFlow.team_id !== team.id) {
                        return res.status(404).json({ error: 'Hog flow not found' })
                    }
                }

                const rerunRequest = req.body as RerunRequest
                const rerunJobId = await this.rerunJobManager.enqueue(team.id, functionKind, id, rerunRequest)

                // Surface the wrapper job in the Invocations list immediately —
                // a 'running' lifecycle row + a `rerun_queued` log line. Both
                // share the same `instance_id = rerun_job_id` so the logs
                // viewer in the row's expand panel picks them up automatically.
                const now = new Date()
                this.invocationResultsService.invocationResultsRowsService.queueRerunWrapperRow({
                    teamId: team.id,
                    parentFunctionKind: functionKind,
                    functionId: id,
                    rerunJobId,
                    status: 'running',
                    pagesProcessed: 0,
                    filter: rerunRequest.filter,
                    scheduledAt: now,
                    startedAt: now,
                })
                const { invocation_ids: invocationIds, ...filterWithoutIds } = rerunRequest.filter
                const filterForLog = invocationIds
                    ? { ...filterWithoutIds, invocation_id_count: invocationIds.length }
                    : filterWithoutIds
                this.invocationResultsService.monitoringService.queueLogs(
                    [
                        {
                            team_id: team.id,
                            log_source: functionKind,
                            log_source_id: id,
                            instance_id: rerunJobId,
                            timestamp: DateTime.fromJSDate(now),
                            level: 'info',
                            message: `Re-run queued. Filter: ${JSON.stringify(filterForLog)}`,
                        },
                    ],
                    functionKind
                )
                await this.invocationResultsService.flush()

                logger.info('⚡️', 'Rerun job enqueued', {
                    function_kind: functionKind,
                    function_id: id,
                    team_id: team.id,
                    rerun_job_id: rerunJobId,
                })
                res.json({ rerun_job_id: rerunJobId, queued_count: 0, skipped_count: 0 })
            } catch (e) {
                logger.error('Error enqueueing rerun job', {
                    error: e instanceof Error ? e.message : String(e),
                })
                res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
            }
        }

    // How many of this workflow's runs are still in flight (parked on waits/delays or actively
    // executing). Django calls this to show publish/edit impact before a live workflow changes.
    private getHogFlowInFlightCount = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }

            const { team_id, id } = req.params
            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            const hogFlow = await this.hogFlowManager.getHogFlow(id)
            if (!hogFlow || hogFlow.team_id !== team.id) {
                return res.status(404).json({ error: 'Workflow not found' })
            }

            const counts = await this.batchResolverProducer.countInFlightJobs(team.id, id)
            return res.json({
                count: counts.count,
                by_action: counts.byAction,
                position_unknown: counts.positionUnknown,
            })
        } catch (e) {
            logger.error('Error counting in-flight hog flow jobs', {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    // Shared gate for the per-call scoped JWTs Django mints (reschedule, cancel): verifies the
    // token and requires its claims to match the URL's team + workflow, so a leaked token can't
    // touch another team or flow. Routes scoped tighter than a workflow (batch cancel) pass the
    // narrower claims via extraClaims and every one must match too; a route without a workflow
    // in its path (step resume) pins the job through extraClaims instead. Writes the 401 itself
    // and returns false on any mismatch.
    // Run a transactional email's workflow once. Django checks the template and the workflow, then calls this
    // once per send. The job goes straight onto the email queue's fast lane.
    //
    // Auth: a per-call JWT minted by Django on its own audience and key, pinned to the team and the workflow,
    // never the fleet-wide internal secret.
    private postTransactionalEmail =
        (schema: z.ZodType<TransactionalEmailRequest, unknown>, tokenClaims: Record<string, string | undefined>) =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            const verificationDeadline = deadlineAfter(ATTACHMENT_VERIFICATION_DEADLINE_MS)
            const stages = new TransactionalEmailStageTimer()
            const reply = (outcome: TransactionalEmailOutcome, status: number, body: Record<string, unknown>) => {
                transactionalEmailRequestsTotal.inc({ outcome })
                return res.status(status).json(body)
            }
            try {
                stages.start('auth')
                if (!this.transactionalEmailJwt.enabled) {
                    return reply('not_configured', 503, {
                        error: 'Transactional email auth not configured (WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET unset)',
                    })
                }
                if (
                    !this.verifyScopedWorkflowJwt(
                        this.transactionalEmailJwt,
                        req,
                        res,
                        'transactional email',
                        tokenClaims
                    )
                ) {
                    transactionalEmailRequestsTotal.inc({ outcome: 'unauthorized' })
                    return
                }
                stages.start('validate')
                const parsed = schema.safeParse(req.body)
                if (!parsed.success) {
                    const issues = parsed.error.issues
                    // Signup accepts some addresses this check refuses, and no retry can fix an address.
                    if (issues.every(isRecipientFormatIssue)) {
                        return reply('recipient_unreachable', 422, { error: 'recipient_unreachable' })
                    }
                    // Paths and codes only: the values include the recipient's address.
                    logger.warn('⚠️', 'Transactional email request failed validation', {
                        team_id: req.params.team_id,
                        hog_flow_id: req.params.id,
                        issues: issues.map((issue) => ({ path: issue.path.join('.'), code: issue.code })),
                    })
                    return reply('invalid_request', 400, { error: parsed.error.message })
                }
                const references = parsed.data.send?.attachments ?? []
                if (references.length > 0 && !this.attachmentUploads.isAllowed(parseInt(req.params.team_id))) {
                    return reply('field_not_accepted', 400, { error: 'field_not_accepted' })
                }

                stages.start('load')
                const teamLookup = this.deps.teamManager.getTeam(parseInt(req.params.team_id)).catch(() => null)
                const hogFlowLookup = this.hogFlowManager.getHogFlowCheckingPrimaryOnMiss(req.params.id)
                // A missing team returns before the workflow lookup is awaited, so its failure must not go unhandled.
                hogFlowLookup.catch(() => undefined)
                const team = await teamLookup
                if (!team) {
                    return reply('not_found', 404, { error: 'Team not found' })
                }
                const hogFlow = await hogFlowLookup
                if (!hogFlow || hogFlow.team_id !== team.id) {
                    return reply('not_found', 404, { error: 'Workflow not found' })
                }
                if (hogFlow.trigger?.type !== 'api') {
                    return reply('not_sendable', 400, { error: 'not_sendable' })
                }
                const filesShape = references.length > 0 ? filesWorkflowShape(hogFlow) : null

                const result = await this.transactionalSendsForRequest().accept(team, hogFlow, parsed.data, stages, {
                    shape: filesShape,
                    sizeMessageBodies: (invocation, emailStep, deadline) =>
                        this.messageBodyBytes(hogFlow, invocation, emailStep, deadline),
                    deadline: verificationDeadline,
                })
                if ('invocationId' in result) {
                    return reply(result.outcome, 202, {
                        status: result.scheduledAt ? 'scheduled' : 'queued',
                        invocation_id: result.invocationId,
                        scheduled_at: result.scheduledAt,
                        replayed: result.outcome === 'replayed',
                        ...result.replyFields,
                    })
                }
                if ('refused' in result) {
                    return reply(result.refused.body.error, result.refused.status, result.refused.body)
                }
                return reply(result.outcome, TRANSACTIONAL_SEND_REFUSAL_STATUS[result.outcome], {
                    error: result.outcome,
                    ...(result.outcome === 'invalid_scheduled_at' && { reason: 'too_far' }),
                })
            } catch (e) {
                logger.error('Error queueing transactional email', {
                    error: e instanceof Error ? e.message : String(e),
                })
                return reply('error', 500, { error: e instanceof Error ? e.message : String(e) })
            } finally {
                stages.finish()
            }
        }

    private async messageBodyBytes(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow,
        emailStep: EmailStep,
        deadline: AbortSignal
    ): Promise<MessageBodySizing> {
        const longUtmValue = emailStep.config.utm_tags_enabled
            ? utmValueOverLimit(emailStep.config.utm_params)
            : undefined
        if (longUtmValue) {
            return { refused: utmValueTooLong(emailStep, longUtmValue) }
        }
        if (liquidTagsInStep(emailStep) > EMAIL_BODY_TAG_LIMIT) {
            return { refused: emailBodyTooManyTags(emailStep) }
        }
        const renderContext = await this.workerRenderContext(hogFlow, invocation)
        deadline.throwIfAborted()
        try {
            return await this.emailStepBodies(hogFlow, invocation, emailStep, renderContext, deadline)
        } catch (error) {
            if (isHogLimitError(error)) {
                return { refused: emailRenderLimitExceeded(emailStep) }
            }
            if (!isHogVMError(error)) {
                throw error
            }
            logger.warn('⚠️', 'Could not render the email step of a send with files', {
                team_id: hogFlow.team_id,
                hog_flow_id: hogFlow.id,
                error: error instanceof Error ? error.name : 'UnknownError',
            })
            return sendBodies(invocation)
        }
    }

    private async workerRenderContext(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<WorkerRenderContext> {
        const [person, groups] = await Promise.all([
            this.recipientPerson(hogFlow, invocation),
            this.groupsManager.getGroupsForEvent(
                hogFlow.team_id,
                invocation.state.event.properties ?? {},
                `${this.config.SITE_URL}/project/${hogFlow.team_id}`
            ),
        ])
        return { person, groups }
    }

    private async recipientPerson(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow
    ): Promise<CyclotronPerson | undefined> {
        const lookup = hogFlowPersonLookup(hogFlow, invocation.state)
        return lookup ? await loadHogFlowPerson(this.personsManager, hogFlow, lookup) : undefined
    }

    private async emailStepBodies(
        hogFlow: HogFlow,
        invocation: CyclotronJobInvocationHogFlow,
        step: EmailStep,
        { person, groups }: WorkerRenderContext,
        deadline: AbortSignal
    ): Promise<MessageBodies> {
        const hogFunction = await this.hogFlowFunctionsService.buildHogFunction(hogFlow, step.config, step.name)
        deadline.throwIfAborted()
        const atEmailStep = {
            ...invocation,
            state: { ...invocation.state, currentAction: { id: step.id, startedAtTimestamp: Date.now() } },
        }
        const rendered = await this.hogFlowFunctionsService.buildHogFunctionInvocation(
            atEmailStep,
            hogFunction,
            { event: invocation.state.event, person, groups, variables: invocation.state.variables },
            deadline
        )
        deadline.throwIfAborted()
        const email = { ...rendered.state.globals.inputs?.email, ...acceptedSendEmailFields(invocation.state.send) }
        return {
            bodyBytes: [
                typeof email.html === 'string' && email.html
                    ? this.sesHtmlMaxBytes(rendered, email.html, email.preheader, deadline)
                    : 0,
                typeof email.text === 'string' ? Buffer.byteLength(email.text) : 0,
            ],
            subject: typeof email.subject === 'string' ? email.subject : '',
        }
    }

    private sesHtmlMaxBytes(
        rendered: CyclotronJobInvocationHogFunction,
        html: string,
        preheader: unknown,
        deadline: AbortSignal
    ): number {
        const utmTags = utmTagsFor(rendered, () => undefined, deadline)
        throwIfDeadlinePassed(deadline)
        return sesHtmlMaxBytes(html, {
            utmTags,
            invocation: rendered,
            signer: this.emailTrackingCodeSigner,
            preheader: typeof preheader === 'string' ? preheader : undefined,
        })
    }

    private postAttachmentUploads = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        if (!this.transactionalEmailJwt.enabled) {
            countUploadRequest('not_configured')
            return res.status(503).json({
                error: 'Transactional email auth not configured (WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET unset)',
            })
        }
        if (
            !this.verifyScopedWorkflowJwt(
                this.transactionalEmailJwt,
                req,
                res,
                'attachment upload',
                ATTACHMENT_UPLOAD_TOKEN_CLAIMS
            )
        ) {
            countUploadRequest('unauthorized')
            return
        }
        const { status, body } = await this.attachmentUploads.prepare(parseInt(req.params.team_id), req.body)
        return res.status(status).json(body)
    }

    private transactionalSendsForRequest(): TransactionalSends {
        return new TransactionalSends({
            siteUrl: this.config.SITE_URL ?? 'http://localhost:8000',
            idempotencyKeys: this.transactionalEmailIdempotencyKeys,
            queue: this.hogflowQueue,
            invocationResultsRows: this.invocationResultsService.invocationResultsRowsService,
            emailStatus: this.emailStatusService,
            teamWorkflowsConfig: this.teamWorkflowsConfigService,
            emailSuppression: this.emailSuppressionService,
            emailValidation: this.emailValidationService,
            quotaLimiting: this.deps.quotaLimiting,
            attachmentUploads: this.attachmentUploads,
        })
    }

    private postTransactionalEmailCancel = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        return await this.manageScheduledSend(req, res, 'cancel', async (sends, teamId, messageId) => {
            const result = await sends.cancel(teamId, messageId)
            switch (result.outcome) {
                case 'canceled':
                    return res.status(200).json({ id: messageId, status: 'canceled' })
                case 'claimed':
                    return res.status(409).json({ error: 'already_sending' })
                case 'not_found':
                    return res.status(404).json({ error: 'not_found' })
            }
        })
    }

    private postTransactionalEmailReschedule = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        return await this.manageScheduledSend(req, res, 'reschedule', async (sends, teamId, messageId) => {
            const parsed = RescheduleRequestSchema.safeParse(req.body)
            if (!parsed.success) {
                return res.status(400).json({ error: 'invalid_request' })
            }
            const result = await sends.reschedule(teamId, messageId, new Date(parsed.data.scheduled_at))
            switch (result.outcome) {
                case 'rescheduled':
                    return res
                        .status(200)
                        .json({ id: messageId, status: 'scheduled', scheduled_at: result.scheduledAt })
                case 'invalid_scheduled_at':
                    return res.status(400).json({ error: 'invalid_scheduled_at', reason: 'too_far' })
                case 'claimed':
                    return res.status(409).json({ error: 'already_sending' })
                case 'canceled':
                    return res.status(409).json({ error: 'canceled' })
                case 'not_found':
                    return res.status(404).json({ error: 'not_found' })
            }
        })
    }

    // Auth: a per-call JWT minted by Django on its own audience, on the transactional email key, pinned to the team,
    // the message and the action, so one token can't cancel or move another send.
    private async manageScheduledSend(
        req: ModifiedRequest,
        res: express.Response,
        label: string,
        handle: (sends: ScheduledTransactionalSends, teamId: number, messageId: string) => Promise<unknown>
    ): Promise<unknown> {
        try {
            if (!this.manageTransactionalEmailJwt.enabled) {
                return res.status(503).json({
                    error: 'Transactional email auth not configured (WORKFLOWS_TRANSACTIONAL_EMAIL_JWT_SECRET unset)',
                })
            }
            if (
                !this.verifyScopedWorkflowJwt(
                    this.manageTransactionalEmailJwt,
                    req,
                    res,
                    `transactional email ${label}`,
                    { message_id: req.params.message_id, action: label }
                )
            ) {
                return
            }
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }
            const sends = new ScheduledTransactionalSends({
                jobs: this.batchResolverProducer,
                hogFlows: this.hogFlowManager,
                invocationResults: this.invocationResultsService,
                emailStatus: this.emailStatusService,
            })
            return await handle(sends, parseInt(req.params.team_id), req.params.message_id)
        } catch (e) {
            logger.error(`Error handling transactional email ${label}`, {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    private verifyScopedWorkflowJwt(
        jwt: ScopedServiceJwt,
        req: ModifiedRequest,
        res: express.Response,
        label: string,
        extraClaims?: Record<string, string | undefined>
    ): boolean {
        const { team_id, id } = req.params
        const authHeader = req.headers['authorization']
        const token =
            typeof authHeader === 'string' && authHeader.startsWith('Bearer ') ? authHeader.slice(7) : undefined
        let claims: Record<string, unknown> | undefined
        try {
            claims = token ? (jwt.verify(token) as typeof claims) : undefined
        } catch {
            claims = undefined
        }
        const extrasMatch = !extraClaims || Object.entries(extraClaims).every(([key, value]) => claims?.[key] === value)
        const flowMatches = id === undefined || claims?.hog_flow_id === id
        if (!claims || claims.team_id !== parseInt(team_id) || !flowMatches || !extrasMatch) {
            res.status(401).json({ error: `Unauthorized: Invalid ${label} token` })
            return false
        }
        return true
    }

    // Pull forward the wake times of this workflow's parked jobs after a timing edit. Django
    // calls this (via a Celery task) when a published/saved change shortened a delay or moved a
    // wait window; one call is one slice, and the caller loops with the returned bounds until
    // `done`. See CyclotronV2Manager.rescheduleParkedJobs for the sweep semantics.
    //
    // Auth: a scoped JWT minted by Django per call, pinned to this team + workflow — NOT the
    // fleet-wide internal secret (the route is exempted from that middleware). Fails closed when
    // the key isn't provisioned.
    private postHogFlowRescheduleParked = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }
            if (!this.rescheduleJwt.enabled) {
                return res.status(503).json({
                    error: 'Reschedule auth not configured (WORKFLOWS_RESCHEDULE_JWT_SECRET unset)',
                })
            }

            const { team_id, id } = req.params

            if (!this.verifyScopedWorkflowJwt(this.rescheduleJwt, req, res, 'reschedule')) {
                return
            }

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            const hogFlow = await this.hogFlowManager.getHogFlow(id)
            if (!hogFlow || hogFlow.team_id !== team.id) {
                return res.status(404).json({ error: 'Workflow not found' })
            }

            const body = req.body ?? {}
            const actionIds = body.action_ids
            if (
                !Array.isArray(actionIds) ||
                actionIds.length === 0 ||
                actionIds.length > 100 ||
                !actionIds.every((a: unknown) => typeof a === 'string' && a.length > 0)
            ) {
                return res.status(400).json({ error: 'action_ids must be a non-empty array of up to 100 strings' })
            }
            const sweepFloor = body.sweep_floor ? new Date(body.sweep_floor) : undefined
            const sweepUntil = body.sweep_until ? new Date(body.sweep_until) : undefined
            if ((sweepFloor && isNaN(sweepFloor.getTime())) || (sweepUntil && isNaN(sweepUntil.getTime()))) {
                return res.status(400).json({ error: 'sweep_floor and sweep_until must be ISO datetimes' })
            }
            if (
                (sweepFloor === undefined) !== (sweepUntil === undefined) ||
                (sweepFloor && sweepUntil && sweepFloor >= sweepUntil)
            ) {
                return res
                    .status(400)
                    .json({ error: 'sweep_floor and sweep_until must be passed together, with floor before until' })
            }

            const result = await this.batchResolverProducer.rescheduleParkedJobs({
                teamId: team.id,
                functionId: id,
                actionIds,
                sweepFloor,
                sweepUntil,
            })
            return res.json({
                swept: result.swept,
                remaining: result.remaining,
                done: result.done,
                sweep_floor: result.sweepFloor.toISOString(),
                sweep_until: result.sweepUntil.toISOString(),
            })
        } catch (e) {
            logger.error('Error rescheduling parked hog flow jobs', {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    /**
     * Wake a batch resolver parked until its realtime cohort finishes calculating. Django calls this
     * once the cohort is ready. `already_resumed` is a success: a second wake for the same run is a no-op.
     * Only a running resolver answers 409, so the caller retries. A finished or removed one already ran, so
     * a wake retried after a lost response gets a 200 and the caller stops.
     */
    private postHogFlowResumeBatchJob = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }
            if (!this.resumeBatchJwt.enabled) {
                return res.status(503).json({
                    error: 'Workflows scoped auth not configured (WORKFLOWS_STEP_RESUME_JWT_SECRET unset)',
                })
            }
            const { team_id, id, batch_job_id } = req.params
            // batch_job_id is pinned in the claims, so a captured token wakes exactly one run.
            if (!this.verifyScopedWorkflowJwt(this.resumeBatchJwt, req, res, 'resume', { batch_job_id })) {
                return
            }
            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }
            if (batch_job_id.length > 200) {
                return res.status(400).json({ error: 'batch_job_id is too long' })
            }
            const outcome = await this.batchResolverProducer.resumeParkedBatchResolver({
                teamId: team.id,
                functionId: id,
                batchJobId: batch_job_id,
            })
            return res.status(outcome === 'job_running' ? 409 : 200).json({ outcome })
        } catch (e) {
            logger.error('Error resuming hog flow batch job', {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    // Wake the parked workflow step that dispatched a task run, with the run's outcome. Django
    // calls this from a retrying Celery task when the run reaches a terminal status. One resume
    // per call; the outcome tells the caller whether to retry (409: the worker still holds the
    // job) or stop (200: delivered, or the step is past this wake).
    //
    // Auth mirrors the cancel routes: a per-call JWT minted by Django on its own audience and key,
    // pinned to the team and to the origin key, so a leaked token can wake exactly one step.
    private postWorkflowStepResume = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }
            if (!this.stepResumeJwt.enabled) {
                return res.status(503).json({
                    error: 'Step resume auth not configured (WORKFLOWS_STEP_RESUME_JWT_SECRET unset)',
                })
            }
            // The token pins the origin key, so read it raw for the claim check; the body is
            // validated only once the caller is allowed to wake this step.
            const originKey = typeof req.body?.origin_key === 'string' ? req.body.origin_key : ''
            if (!this.verifyScopedWorkflowJwt(this.stepResumeJwt, req, res, 'step resume', { origin_key: originKey })) {
                return
            }
            const parsed = WorkflowStepResumeSchema.safeParse(req.body)
            const key = parsed.success ? parseWorkflowStepDispatchKey(parsed.data.origin_key) : null
            if (!parsed.success || !key) {
                return res.status(400).json({ error: 'origin_key must be a workflow step dispatch key' })
            }
            const teamId = parseInt(req.params.team_id)
            const team = await this.deps.teamManager.getTeam(teamId).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            const outcomes = await this.batchResolverProducer.resumeParkedSteps(teamId, [{ ...parsed.data, ...key }])
            const outcome = outcomes.get(key.jobId) ?? 'job_missing'
            return res.status(outcome === 'job_running' ? 409 : 200).json({ outcome })
        } catch (e) {
            logger.error('Error resuming workflow step', {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    // Flag a workflow's in-flight cyclotron jobs for cancellation. The workers own the actual
    // termination (terminal status + lifecycle row + metric + log) when they observe the flag;
    // this endpoint only marks rows and wakes parked ones. See CyclotronV2Manager.cancelJobs.
    //
    // Auth mirrors postHogFlowRescheduleParked: a per-call JWT minted by Django, pinned to this
    // team + workflow, on its own audience, never the fleet-wide internal secret.
    private postHogFlowCancelInvocations = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }
            if (!this.cancelInvocationsJwt.enabled) {
                return res.status(503).json({
                    error: 'Workflows scoped auth not configured (WORKFLOWS_CANCEL_JWT_SECRET unset)',
                })
            }

            const { team_id, id } = req.params

            if (!this.verifyScopedWorkflowJwt(this.cancelInvocationsJwt, req, res, 'cancel')) {
                return
            }

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            // Deliberately no hogFlowManager lookup beyond team pinning: cancel must keep working
            // for flows that were deleted with runs still parked. The JWT claims already bind the
            // request to this flow id, and cancelJobs filters on (team_id, function_id).

            // UUID-shaped ids only: cancelJobs binds them as ::uuid[], so a malformed id must be a
            // 400 here rather than a Postgres cast error surfaced as a 500. Match the shape only:
            // invocation ids are UUIDTs, whose version and variant nibbles carry a series counter
            // and random bytes, so a version-aware check rejects every real id. The cap is the same
            // env-driven one the Django cancel serializer validates against, so raising the env
            // var lifts both sides together instead of leaving Django accepting ids this route
            // then rejects with a 400 (which Django surfaces as a 500).
            const maxInvocationIds = this.config.HOG_INVOCATION_RERUN_MAX_COUNT
            const idsMessage = `invocation_ids must be a non-empty array of up to ${maxInvocationIds} invocation UUIDs`
            const parsed = z
                .object({
                    invocation_ids: z
                        .array(z.string().refine((id) => UUID.validateString(id, false), idsMessage))
                        .min(1, idsMessage)
                        .max(maxInvocationIds, idsMessage)
                        .optional(),
                    all: z.boolean().optional(),
                })
                .refine((body) => (body.invocation_ids !== undefined) !== (body.all === true), {
                    message: 'Provide exactly one of invocation_ids or all=true',
                })
                .safeParse(req.body ?? {})
            if (!parsed.success) {
                return res.status(400).json({ error: parsed.error.issues[0]?.message ?? 'Invalid request body' })
            }
            const { invocation_ids: invocationIds, all } = parsed.data

            const result = await this.batchResolverProducer.cancelJobs({
                teamId: team.id,
                functionId: id,
                jobIds: invocationIds,
                all: all === true ? true : undefined,
                // Batch-resolver jobs orchestrate audience fan-out rather than being runs;
                // flagging one would silently stall a batch with no terminal reporting.
                // Stopping a batch run is its own feature with its own endpoint.
                excludeQueueNames: [HOGFLOW_BATCH_RESOLVE_QUEUE],
            })
            return res.json({
                marked: result.marked,
                remaining: result.remaining,
                done: result.done,
            })
        } catch (e) {
            logger.error('Error cancelling hog flow invocations', {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    // Stop a batch run: flag its resolver orchestration job and every child run for
    // cancellation in one sweep — they share parent_run_id, so one selector covers both.
    // The resolver's in-transaction tombstone check plus Django's repeat-until-done loop
    // make this converge: once the resolver is flagged it can commit at most the one page
    // that already held its row lock, and that page's children surface in the next sweep's
    // remaining count.
    //
    // Auth mirrors the other workflows CDP calls: a per-call JWT minted by Django, pinned
    // to this team + workflow, on its own audience.
    private postHogFlowCancelBatchJob = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            if (!this.batchResolverProducer) {
                return res.status(503).json({
                    error: 'Cyclotron producer not initialized (CYCLOTRON_NODE_DATABASE_URL unset)',
                })
            }
            if (!this.cancelBatchJwt.enabled) {
                return res.status(503).json({
                    error: 'Workflows scoped auth not configured (WORKFLOWS_CANCEL_JWT_SECRET unset)',
                })
            }

            const { team_id, id, batch_job_id } = req.params

            // batch_job_id is pinned in the claims too: without it, a captured token could stop
            // any sibling batch of the same workflow for the token's lifetime.
            if (!this.verifyScopedWorkflowJwt(this.cancelBatchJwt, req, res, 'cancel', { batch_job_id })) {
                return
            }

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)
            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            if (batch_job_id.length > 200) {
                return res.status(400).json({ error: 'batch_job_id is too long' })
            }

            const result = await this.batchResolverProducer.cancelJobs({
                teamId: team.id,
                functionId: id,
                parentRunId: batch_job_id,
            })
            return res.json({
                marked: result.marked,
                remaining: result.remaining,
                done: result.done,
            })
        } catch (e) {
            logger.error('Error cancelling hog flow batch job', {
                error: e instanceof Error ? e.message : String(e),
            })
            return res.status(500).json({ error: e instanceof Error ? e.message : String(e) })
        }
    }

    private postHogFlowBatchInvocation = async (req: ModifiedRequest, res: express.Response): Promise<any> => {
        try {
            const { id, team_id, parent_run_id } = req.params

            logger.info('⚡️', 'Received hogflow batch invocation', { id, team_id, parent_run_id })

            const team = await this.deps.teamManager.getTeam(parseInt(team_id)).catch(() => null)

            if (!team) {
                return res.status(404).json({ error: 'Team not found' })
            }

            const hogFlow = await this.hogFlowManager.getHogFlow(id)

            if (!hogFlow || hogFlow.team_id !== team.id) {
                return res.status(404).json({ error: 'Workflow not found' })
            }

            if (hogFlow.trigger.type !== 'batch') {
                return res.status(400).json({ error: 'Only batch Workflows are supported for batch jobs' })
            }

            const maxAudienceSize =
                typeof req.body.max_audience_size === 'number' ? req.body.max_audience_size : undefined

            if (!this.batchResolverProducer) {
                throw new Error('Batch resolver producer is not configured (missing CYCLOTRON_NODE_DATABASE_URL)')
            }

            const realtimeCohort = parseRealtimeCohort(req.body.realtime_cohort)
            if (realtimeCohort === null) {
                return res.status(400).json({ error: 'realtime_cohort.wait_until must be an ISO 8601 date' })
            }

            const snapshotFilters: BatchResolverState['filters'] | undefined = req.body.filters
            const audienceType = snapshotFilters?.audience_type ?? hogFlow.trigger.filters.audience_type
            // A snapshot saved before assignment statuses existed carries assignee ids or the legacy
            // flag, but no status. Resolved key by key, it inherits the live trigger's status, and
            // Django rejects a status paired with assignee ids, so the run fails instead of sending
            // the audience the confirm check validated. One source answers for all three keys.
            const assignmentFilters =
                snapshotFilters && ASSIGNMENT_FILTER_KEYS.some((key) => snapshotFilters[key] !== undefined)
                    ? snapshotFilters
                    : hogFlow.trigger.filters
            const assignmentStatus = assignmentFilters.assignment_status
            const initialState: BatchResolverState = {
                batchJobId: parent_run_id,
                teamId: team.id,
                hogFlowId: hogFlow.id,
                filters: {
                    // Prefer the audience snapshot validated at dispatch time - re-reading the live
                    // trigger here would let an edit landing after the confirm check widen the send.
                    // Fallback covers callers that predate the snapshot.
                    audience_type: audienceType,
                    properties: snapshotFilters?.properties ?? (hogFlow.trigger.filters.properties || []),
                    filter_test_accounts:
                        snapshotFilters?.filter_test_accounts ??
                        (hogFlow.trigger.filters.filter_test_accounts || false),
                    tag_names: snapshotFilters?.tag_names ?? hogFlow.trigger.filters.tag_names,
                    assignment_status: assignmentStatus,
                    assigned_to_user_ids: assignmentFilters.assigned_to_user_ids,
                    all_roles_unassigned: assignmentStatus ? undefined : assignmentFilters.all_roles_unassigned,
                },
                variables: req.body.variables ?? {},
                groupTypeIndex: typeof req.body.group_type_index === 'number' ? req.body.group_type_index : undefined,
                // Only dedupe by email when every email action's `to` template is exactly the default
                // `{{ person.properties.email }}`. Custom recipients (work_email, computed Liquid, static
                // strings) would make the dedupe key diverge from the actual send target — better to skip
                // dedupe than dedupe wrongly. Also skip when the flow has no email action at all.
                // Account audiences carry no person (and external ids are already unique), so never dedupe.
                dedupeKey: audienceType !== 'accounts' && canDedupeByEmail(hogFlow) ? ('email' as const) : undefined,
                realtimeCohort,
                maxAudienceSize: maxAudienceSize ?? this.config.CDP_BATCH_WORKFLOW_MAX_AUDIENCE_SIZE,
                cursor: null,
                totalEnqueued: 0,
                pagesProcessed: 0,
                attempts: 0,
                startedAt: new Date().toISOString(),
            }
            const waitUntil = initialState.realtimeCohort?.waitUntil
            await this.batchResolverProducer.createJob({
                teamId: team.id,
                queueName: HOGFLOW_BATCH_RESOLVE_QUEUE,
                parentRunId: parent_run_id,
                functionId: hogFlow.id,
                state: serializeResolverState(initialState),
                // A cohort that is still calculating parks the job until Django resumes it.
                ...(waitUntil ? { scheduled: new Date(waitUntil) } : {}),
            })
            if (waitUntil) {
                counterBatchResolverParked.inc()
            }

            res.json({ status: 'queued' })
        } catch (e) {
            logger.error('Error handling hogflow batch invocation', { error: e })
            res.status(500).json({ error: [e.message] })
        }
    }

    private async processAndRespondToWebhook(
        webhookId: string,
        req: ModifiedRequest,
        res: express.Response,
        onSuccess: (
            result: Awaited<ReturnType<typeof this.cdpSourceWebhooksConsumer.processWebhook>>
        ) => Promise<any> | any
    ): Promise<any> {
        try {
            const result = await this.cdpSourceWebhooksConsumer.processWebhook(webhookId, req)

            if (typeof result.execResult === 'object' && result.execResult && 'httpResponse' in result.execResult) {
                const httpResponse = result.execResult.httpResponse as HogFunctionWebhookResult

                // Security headers to prevent XSS via content-type injection
                res.set('X-Content-Type-Options', 'nosniff')
                res.set('Content-Security-Policy', "default-src 'none'")

                if (typeof httpResponse.body === 'string') {
                    const safeContentType = sanitizeContentType(
                        httpResponse.contentType,
                        httpResponse.isBase64Encoded ? 'application/octet-stream' : 'text/plain'
                    )
                    if (httpResponse.isBase64Encoded) {
                        const buffer = Buffer.from(httpResponse.body, 'base64')
                        return res.status(httpResponse.status).type(safeContentType).send(buffer)
                    }
                    return res.status(httpResponse.status).type(safeContentType).send(httpResponse.body)
                } else if (typeof httpResponse.body === 'object') {
                    return res.status(httpResponse.status).json(httpResponse.body)
                }
                return res.status(httpResponse.status).send('')
            }

            return await onSuccess(result)
        } catch (error) {
            if (error instanceof SourceWebhookError) {
                return res.status(error.status).json({ error: error.message })
            }
            logger.error('[CdpApi] Error handling webhook', { error })
            return res.status(500).json({ error: 'Internal error' })
        }
    }

    private handleWebhook =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            const { webhook_id } = req.params
            return this.processAndRespondToWebhook(webhook_id, req, res, (result) => {
                if (result.error) {
                    return res.status(500).json({ status: 'Unhandled error' })
                }
                if (!result.finished) {
                    return res.status(201).json({ status: 'queued' })
                }
                return res.status(200).json({ status: 'ok' })
            })
        }

    private handleWarehouseSourceWebhook =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            const { webhook_id } = req.params
            return this.processAndRespondToWebhook(webhook_id, req, res, (result) => {
                if (result.error) {
                    return res.status(500).json({ error: 'Internal error' })
                }
                if (!result.finished) {
                    return res.status(201).json({ status: 'queued' })
                }
                return res.status(200).json({ status: 'ok' })
            })
        }

    private postSesWebhook =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            try {
                const { status, message } = await this.emailTrackingService.handleSesWebhook(req)
                return res.status(status).json({ message })
            } catch {
                return res.status(500).json({ error: 'Internal error' })
            }
        }

    private getEmailTrackingPixel =
        () =>
        (req: ModifiedRequest, res: express.Response): any => {
            this.emailTrackingService.handleEmailTrackingPixel(req, res)
        }

    private getEmailTrackingRedirect =
        () =>
        (req: ModifiedRequest, res: express.Response): any => {
            this.emailTrackingService.handleEmailTrackingRedirect(req, res)
        }

    private generatePreferencesToken =
        () =>
        (req: ModifiedRequest, res: express.Response): any => {
            const { team_id, identifier } = req.body

            if (!team_id || !identifier) {
                return res.status(400).json({ error: 'Team ID and identifier are required' })
            }

            const token = this.recipientTokensService.generatePreferencesToken({
                team_id,
                identifier,
            })
            return res.status(200).json({ token })
        }

    private validatePreferencesToken =
        () =>
        (req: ModifiedRequest, res: express.Response): any => {
            try {
                const { token } = req.params

                if (!token) {
                    return res.status(400).json({ error: 'Token is required' })
                }

                const result = this.recipientTokensService.validatePreferencesToken(token)

                if (!result.valid) {
                    return res.status(400).json({ error: 'Invalid or expired token' })
                }

                return res.status(200).json(result)
            } catch (error) {
                logger.error('[CdpApi] Error validating preferences token', error)
                return res.status(500).json({ error: 'Failed to validate token' })
            }
        }

    private handleBatchExportHogFunction =
        () =>
        async (req: ModifiedRequest, res: express.Response): Promise<any> => {
            try {
                const result = await this.batchExportHogFunctionService.execute(
                    {
                        team_id: req.params.team_id,
                        hog_function_id: req.params.hog_function_id,
                    },
                    req.body
                )

                return res.json({
                    status: result.error ? 'error' : 'success',
                    errors: result.error ? [String(result.error)] : [],
                    logs: result.logs,
                })
            } catch (e) {
                if (e instanceof NotFoundError) {
                    return res.status(404).json({ errors: [e.message] })
                } else if (e instanceof ParseError) {
                    return res.status(400).json({ errors: [e.message] })
                } else {
                    console.error(e)
                    return res.status(500).json({ errors: [e.message] })
                }
            }
        }
}

const buildHogExecutorAsyncOptions = (
    mockAsyncFunctions: boolean,
    logs: MinimalLogEntry[],
    sensitiveValues?: string[]
): HogExecutorExecuteAsyncOptions => {
    let mockFunctions: Record<string, (...args: any[]) => any> | undefined

    if (mockAsyncFunctions) {
        mockFunctions = {}
        for (const name of getRegisteredAsyncFunctionNames()) {
            const handler = getAsyncFunctionHandler(name)!
            mockFunctions[name] = (...args: any[]) => {
                const startIndex = logs.length
                const result = handler.mock(args, logs)
                if (sensitiveValues?.length) {
                    for (let i = startIndex; i < logs.length; i++) {
                        logs[i] = {
                            ...logs[i],
                            message: sanitizeLogMessage([logs[i].message], sensitiveValues),
                        }
                    }
                }
                return result
            }
        }
    }

    return {
        maxAsyncFunctions: MAX_ASYNC_STEPS,
        asyncFunctionsNames: mockAsyncFunctions ? [] : undefined,
        functions: mockFunctions,
    }
}
