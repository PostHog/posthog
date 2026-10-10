import { PostHogError } from '../errors.js'
import type { JsonValue, PostHogClientOptions, ProjectContext, RequestOptions } from '../types.js'
import { type ResolvedConfig, resolveConfig, validateProjectId } from './config.js'
import { isObject, request, waitWithSignal, withDeadline } from './http.js'
import {
    type OperationDefinition,
    buildRequest,
    transformResponse,
    validateInput,
    validateOutput,
} from './operation.js'
import type { SharedToolSession } from './shared-tools.js'

function metadataError(): never {
    throw new PostHogError({
        kind: 'response_validation',
        message: 'PostHog returned invalid credential or user metadata.',
    })
}

function ids(value: unknown): number[] {
    if (value === null || value === undefined) {
        return []
    }
    if (!Array.isArray(value) || value.some((id) => !Number.isSafeInteger(id) || id <= 0)) {
        return metadataError()
    }
    return [...new Set(value as number[])]
}

export class Runtime {
    private config?: ResolvedConfig
    private selected?: ProjectContext
    private discovery: Promise<ProjectContext> | undefined
    private readonly options: PostHogClientOptions
    private toolSession: Promise<SharedToolSession> | undefined
    private switchedProject?: ProjectContext

    constructor(
        options: PostHogClientOptions = {},
        private readonly parent?: Runtime,
        private readonly projectId?: number
    ) {
        this.options = { ...options }
    }

    private configuration(): ResolvedConfig {
        this.config ??= this.parent ? this.parent.configuration() : resolveConfig(this.options)
        return this.config
    }

    scope(projectId: number): Runtime {
        return new Runtime({}, this, validateProjectId(projectId))
    }

    async context(options: RequestOptions = {}): Promise<ProjectContext> {
        const config = this.configuration()
        return withDeadline(options, config.timeoutMs, async (signal) => ({ ...(await this.project(signal)) }))
    }

    private async project(signal: AbortSignal): Promise<ProjectContext> {
        if (this.projectId !== undefined) {
            return { projectId: this.projectId, source: 'explicit' }
        }
        if (this.switchedProject) {
            return this.switchedProject
        }
        const config = this.configuration()
        if (config.project) {
            return config.project
        }
        if (this.selected) {
            return this.selected
        }
        if (!this.discovery) {
            // Discovery has its own deadline: one canceled caller must not cancel the other waiters.
            this.discovery = withDeadline({}, config.timeoutMs, (discoverySignal) =>
                this.discover(config, discoverySignal)
            )
                .then((context) => {
                    this.selected = context
                    return context
                })
                .finally(() => {
                    this.discovery = undefined
                })
        }
        return waitWithSignal(this.discovery, signal)
    }

    async executeTool<T>(toolName: string, input: unknown, options: RequestOptions = {}): Promise<T> {
        const config = this.configuration()
        return withDeadline(options, config.timeoutMs, async (signal) => {
            this.toolSession ??= import('../generated/handlers.mjs').then(({ createToolSession }) =>
                createToolSession({
                    baseUrl: config.baseUrl,
                    publicBaseUrl: config.publicBaseUrl,
                    ...(config.token ? { token: config.token } : {}),
                    ...(this.projectId !== undefined
                        ? { pinnedProjectId: this.projectId }
                        : config.organizationId
                          ? { organizationId: config.organizationId }
                          : {}),
                    ...(config.taskId ? { taskId: config.taskId } : {}),
                    ...(config.feedback ? { feedback: config.feedback } : {}),
                    getProjectId: async (callSignal) => (await this.project(callSignal)).projectId,
                    setContext: (context) => {
                        if (
                            this.projectId !== undefined &&
                            context.projectId !== undefined &&
                            context.projectId !== this.projectId
                        ) {
                            throw new PostHogError({
                                kind: 'configuration',
                                message:
                                    'This client has an immutable project scope. Use client.project(id) to select another project.',
                            })
                        }
                        if (context.projectId !== undefined) {
                            this.switchedProject = {
                                projectId: validateProjectId(context.projectId),
                                source: 'explicit',
                                ...(context.organizationId ? { organizationId: context.organizationId } : {}),
                            }
                        }
                    },
                    fetch: async (url, init, callSignal) => {
                        if (!url.startsWith(`${config.baseUrl}/`)) {
                            throw new PostHogError({
                                kind: 'configuration',
                                message: 'The tool attempted to send a request outside the configured PostHog API.',
                            })
                        }
                        const headers = new Headers(init.headers)
                        if (!headers.has('Accept')) {
                            headers.set('Accept', 'application/json')
                        }
                        if (init.body && !headers.has('Content-Type')) {
                            headers.set('Content-Type', 'application/json')
                        }
                        if (config.authMode === 'token') {
                            headers.set('Authorization', `Bearer ${config.token}`)
                        } else {
                            headers.delete('Authorization')
                        }
                        headers.set('X-PostHog-Client', 'sdk')
                        if (config.taskId) {
                            headers.set('X-PostHog-Task-Id', config.taskId)
                        }
                        return waitWithSignal(
                            config.fetch(url, { ...init, headers, signal: callSignal, redirect: 'error' }),
                            callSignal
                        )
                    },
                })
            )
            try {
                const session = await this.toolSession
                return (await session.execute(toolName, input, signal)) as T
            } catch (cause) {
                if (signal.aborted) {
                    throw signal.reason
                }
                if (cause instanceof PostHogError) {
                    throw cause
                }
                let error: unknown = cause
                let transportError = false
                while (isObject(error)) {
                    transportError ||= error.name === 'PostHogTransportError'
                    if (!error.cause || 'status' in error) {
                        break
                    }
                    error = error.cause
                }
                const sdkMeta = isObject(cause) && isObject(cause.sdkMeta) ? cause.sdkMeta : undefined
                const status =
                    isObject(error) && typeof error.status === 'number'
                        ? error.status
                        : typeof sdkMeta?.status === 'number' && sdkMeta.status >= 400
                          ? sdkMeta.status
                          : undefined
                const issues = isObject(cause) && Array.isArray(cause.issues) ? cause.issues : undefined
                const kind =
                    isObject(cause) && cause.kind === 'configuration'
                        ? 'configuration'
                        : issues
                          ? 'input_validation'
                          : status
                            ? 'api'
                            : transportError
                              ? 'transport'
                              : 'tool'
                throw new PostHogError(
                    {
                        kind,
                        message: cause instanceof Error ? cause.message : 'The PostHog tool failed.',
                        ...(status ? { status } : {}),
                        ...(typeof sdkMeta?.requestId === 'string' ? { requestId: sdkMeta.requestId } : {}),
                        ...(isObject(error) && typeof error.retryAfterSeconds === 'number'
                            ? { retryAfterMs: error.retryAfterSeconds * 1000 }
                            : {}),
                        ...(issues
                            ? {
                                  fields: issues.map((issue) => ({
                                      path: issue.path ?? [],
                                      code: issue.code ?? 'invalid',
                                      message: issue.message,
                                  })),
                              }
                            : {}),
                    },
                    { cause }
                )
            }
        })
    }

    private async discover(config: ResolvedConfig, signal: AbortSignal): Promise<ProjectContext> {
        if (config.authMode === 'proxy') {
            throw new PostHogError({
                kind: 'project_resolution',
                message: 'Tasks proxy authentication requires projectId or POSTHOG_PROJECT_ID.',
                projectResolution: { reason: 'missing', candidateProjectIds: [] },
            })
        }
        const tokenType =
            config.tokenType ??
            (config.token?.startsWith('phx_')
                ? 'personal_api_key'
                : config.token?.startsWith('pha_')
                  ? 'oauth'
                  : undefined)
        if (!tokenType) {
            throw new PostHogError({
                kind: 'project_resolution',
                message: 'Set tokenType for project discovery, or specify projectId directly.',
                projectResolution: { reason: 'discovery_unavailable', candidateProjectIds: [] },
            })
        }
        const result =
            tokenType === 'personal_api_key'
                ? await request(config, '/api/personal_api_keys/@current', { method: 'GET' }, signal)
                : await request(
                      config,
                      '/oauth/introspect',
                      {
                          method: 'POST',
                          headers: { 'Content-Type': 'application/json' },
                          body: JSON.stringify({ token: config.token }),
                      },
                      signal
                  )
        if (!isObject(result.data)) {
            metadataError()
        }
        if (tokenType === 'oauth' && result.data.active !== true) {
            throw new PostHogError({
                kind: 'api',
                message: 'The OAuth access token is inactive.',
                status: 401,
                code: 'inactive_token',
            })
        }
        const projects = ids(result.data.scoped_teams)
        if (projects.length === 1) {
            return { projectId: projects[0]!, source: 'token_scope' }
        }
        const organizations = result.data.scoped_organizations ?? []
        if (!Array.isArray(organizations) || organizations.some((id) => typeof id !== 'string')) {
            metadataError()
        }
        let user: JsonValue
        try {
            user = (await request(config, '/api/users/@me/', { method: 'GET' }, signal)).data
        } catch (cause) {
            if (!(cause instanceof PostHogError) || cause.details.status !== 403) {
                throw cause
            }
            throw new PostHogError(
                {
                    kind: 'project_resolution',
                    message:
                        'Project discovery needs user:read. Specify projectId to use this credential without that lookup.',
                    status: 403,
                    projectResolution: { reason: 'discovery_unavailable', candidateProjectIds: projects },
                },
                { cause }
            )
        }
        if (!isObject(user)) {
            metadataError()
        }
        const team = user.team
        if (isObject(team) && Number.isSafeInteger(team.id) && Number(team.id) > 0) {
            const allowed = projects.length
                ? projects.includes(Number(team.id))
                : !organizations.length ||
                  (typeof team.organization === 'string' && organizations.includes(team.organization))
            if (allowed) {
                return {
                    projectId: Number(team.id),
                    source: 'user_selection',
                    ...(typeof team.organization === 'string' ? { organizationId: team.organization } : {}),
                }
            }
        }
        throw new PostHogError({
            kind: 'project_resolution',
            message: 'No permitted default project could be selected. Specify projectId or use client.project(id).',
            projectResolution: { reason: projects.length > 1 ? 'ambiguous' : 'missing', candidateProjectIds: projects },
        })
    }

    async execute<T>(operation: OperationDefinition, input: unknown, options: RequestOptions = {}): Promise<T> {
        const config = this.configuration()
        return withDeadline(options, config.timeoutMs, async (signal) => {
            const params = validateInput(operation, input)
            const project =
                operation.path.includes('{project_id}') || operation.list || operation.enrichUrl
                    ? await this.project(signal)
                    : undefined
            if (operation.query?.filterTestAccounts && params.filterTestAccounts === undefined) {
                let settings: JsonValue
                try {
                    settings = (
                        await request(config, `/api/projects/${project!.projectId}/`, { method: 'GET' }, signal)
                    ).data
                } catch (cause) {
                    if (!(cause instanceof PostHogError) || cause.details.status !== 403) {
                        throw cause
                    }
                    throw new PostHogError(
                        {
                            kind: 'input_validation',
                            message:
                                'Specify filterTestAccounts explicitly: this credential cannot read the project default.',
                            status: 403,
                        },
                        { cause }
                    )
                }
                if (!isObject(settings) || typeof settings.test_account_filters_default_checked !== 'boolean') {
                    throw new PostHogError({
                        kind: 'response_validation',
                        message: 'PostHog returned an invalid test-account filtering default.',
                    })
                }
                params.filterTestAccounts = settings.test_account_filters_default_checked
            }
            const { path, init } = buildRequest(operation, params, project)
            const result = await request(config, path, init, signal)
            const output = transformResponse(operation, result.data, params, config, project, result.meta)
            return validateOutput<T>(operation, output, result.meta)
        })
    }
}
