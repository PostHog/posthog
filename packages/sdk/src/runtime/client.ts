import manifest from '../../package.json' with { type: 'json' }
import { PostHogError } from '../errors.js'
import type { JsonValue, PostHogClientOptions, ProjectContext, RequestOptions } from '../types.js'
import { type ResolvedConfig, resolveConfig, validateProjectId } from './config.js'
import { isObject, request, waitWithSignal, withDeadline } from './http.js'
import type { ApiToolLibrary } from './tool-library.mjs'

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
    private active: ProjectContext | undefined
    private selected?: ProjectContext
    private discovery: Promise<ProjectContext> | undefined
    private readonly options: PostHogClientOptions
    private library?: Promise<ApiToolLibrary>

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

    async runWithDeadline<T>(
        options: RequestOptions | undefined,
        run: (signal: AbortSignal) => Promise<T>
    ): Promise<T> {
        const config = this.configuration()
        return withDeadline(options ?? {}, config.timeoutMs, run)
    }

    scope(projectId: number): Runtime {
        return new Runtime({}, this, validateProjectId(projectId))
    }

    async context(options: RequestOptions = {}): Promise<ProjectContext> {
        const config = this.configuration()
        return withDeadline(options, config.timeoutMs, async (signal) => ({
            ...(this.active ?? (await this.project(signal))),
        }))
    }

    private async project(signal: AbortSignal): Promise<ProjectContext> {
        if (this.projectId !== undefined) {
            return { projectId: this.projectId, source: 'explicit' }
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

    private toolLibrary(): Promise<ApiToolLibrary> {
        if (this.parent) {
            return this.parent.toolLibrary()
        }
        const config = this.configuration()
        this.library ??= import('./tool-library.mjs').then(({ createApiToolLibrary }) =>
            createApiToolLibrary({
                fetch: config.fetch,
                onProjectSelected: (id, org) => {
                    const projectId = Number(id)
                    if (projectId !== (config.project?.projectId ?? this.selected?.projectId)) {
                        this.active = { projectId, source: 'explicit', ...(org ? { organizationId: org } : {}) }
                    } else {
                        this.active = undefined
                    }
                },
            })
        )
        return this.library
    }

    async executeTool<T>(toolName: string, input: unknown, options: RequestOptions = {}): Promise<T> {
        return this.runWithDeadline(options, async (signal) => {
            const config = this.configuration()
            const library = await this.toolLibrary()
            const project = await this.project(signal)
            const result = await library.call(
                toolName,
                input as Record<string, unknown>,
                {
                    apiKey: config.token ?? '',
                    host: config.baseUrl,
                    authMode: config.authMode,
                    publicBaseUrl: config.publicBaseUrl,
                    ...(this.projectId !== undefined || config.authMode === 'proxy'
                        ? { projectId: String(project.projectId) }
                        : { initialProjectId: String(project.projectId) }),
                    ...(config.organizationId ? { organizationId: config.organizationId } : {}),
                    ...(config.taskId ? { taskId: config.taskId } : {}),
                    clientName: 'sdk',
                    clientVersion: manifest.version,
                },
                options.confirm === true,
                { signal }
            )
            signal.throwIfAborted()
            if (!result.ok) {
                const { code, message, status, detail, missingScope } = result.error
                throw new PostHogError({
                    kind: 'tool',
                    code,
                    message,
                    ...(status !== undefined ? { status } : {}),
                    ...(detail ? { body: detail } : {}),
                    ...(missingScope ? { missingScope } : {}),
                })
            }
            const value = result.value
            if (isObject(value) && value.isError === true && Array.isArray(value.content)) {
                const message = value.content
                    .filter(isObject)
                    .map((item) => item.text)
                    .filter((text) => typeof text === 'string')
                    .join('\n')
                throw new PostHogError({
                    kind: 'tool',
                    code: 'tool_error',
                    message: message || 'The PostHog tool failed.',
                })
            }
            return value as T
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
}
