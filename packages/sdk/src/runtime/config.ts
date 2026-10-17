import { PostHogError } from '../errors.js'
import type { PostHogClientOptions, ProjectContext } from '../types.js'

export interface ResolvedConfig {
    baseUrl: string
    publicBaseUrl: string
    authMode: 'token' | 'proxy'
    token?: string
    tokenType?: 'personal_api_key' | 'oauth'
    project: ProjectContext | undefined
    fetch: typeof globalThis.fetch
    timeoutMs: number
    organizationId?: string
    taskId?: string
    feedback?: PostHogClientOptions['feedback']
}

export function configurationError(message: string): never {
    throw new PostHogError({ kind: 'configuration', message })
}

export function validateProjectId(value: number): number {
    if (!Number.isSafeInteger(value) || value <= 0) {
        configurationError('projectId must be a positive safe integer.')
    }
    return value
}

export function validateTimeout(value: number): number {
    if (!Number.isFinite(value) || value <= 0 || value > 2_147_483_647) {
        configurationError('timeoutMs must be greater than zero and no larger than 2147483647.')
    }
    return value
}

function baseUrl(value: string, name: string): string {
    let url: URL
    try {
        url = new URL(value)
    } catch {
        return configurationError(`${name} must be an absolute HTTP or HTTPS URL.`)
    }
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
        configurationError(`${name} must be an HTTP or HTTPS URL without credentials, a query, or a fragment.`)
    }
    return url.toString().replace(/\/+$/, '')
}

export function resolveConfig(options: PostHogClientOptions): ResolvedConfig {
    const env = options.env === false || typeof process === 'undefined' ? {} : process.env
    const authMode = options.authMode ?? env.POSTHOG_AUTH_MODE ?? 'token'
    if (authMode !== 'token' && authMode !== 'proxy') {
        configurationError('authMode / POSTHOG_AUTH_MODE must be token or proxy.')
    }
    const configuredUrl = options.baseUrl ?? (env.POSTHOG_API_URL || env.POSTHOG_HOST)
    const publicUrl = options.publicBaseUrl ?? env.POSTHOG_PUBLIC_URL
    if (authMode === 'proxy' && (!configuredUrl || !publicUrl)) {
        configurationError(
            'Proxy authentication requires baseUrl / POSTHOG_API_URL and publicBaseUrl / POSTHOG_PUBLIC_URL.'
        )
    }
    if (authMode === 'proxy' && options.token !== undefined) {
        configurationError('A token cannot be combined with proxy authentication. The proxy supplies the credential.')
    }
    const token =
        authMode === 'token' ? (options.token ?? (env.POSTHOG_PERSONAL_API_KEY || env.POSTHOG_API_KEY)) : undefined
    if (authMode === 'token' && (!token || /\s/.test(token) || token.startsWith('phc_'))) {
        configurationError(
            'Provide a personal API key or OAuth token in token / POSTHOG_PERSONAL_API_KEY, or configure Tasks proxy authentication.'
        )
    }
    const explicitProject = options.projectId
    const organizationId = options.organizationId ?? env.POSTHOG_ORGANIZATION_ID
    const taskId = options.taskId ?? env.POSTHOG_TASK_ID
    const environmentProject = env.POSTHOG_PROJECT_ID
    const apiUrl = baseUrl(configuredUrl ?? 'https://us.posthog.com', 'baseUrl')
    const fetch = options.fetch ?? globalThis.fetch
    if (typeof fetch !== 'function') {
        configurationError('Provide a fetch implementation or use Node.js 22 or later.')
    }
    return {
        baseUrl: apiUrl,
        publicBaseUrl: baseUrl(publicUrl || apiUrl, 'publicBaseUrl'),
        authMode,
        ...(token ? { token } : {}),
        ...(options.tokenType ? { tokenType: options.tokenType } : {}),
        ...(organizationId ? { organizationId } : {}),
        ...(taskId ? { taskId } : {}),
        ...(options.feedback ? { feedback: options.feedback } : {}),
        // Validate only when used, so an explicit client.project(id) takes precedence over this default.
        get project(): ProjectContext | undefined {
            if (explicitProject !== undefined) {
                return { projectId: validateProjectId(explicitProject), source: 'explicit' }
            }
            if (environmentProject !== undefined) {
                if (!/^[1-9]\d*$/.test(environmentProject)) {
                    configurationError('POSTHOG_PROJECT_ID must contain a positive integer.')
                }
                return { projectId: validateProjectId(Number(environmentProject)), source: 'environment' }
            }
            return undefined
        },
        fetch,
        timeoutMs: validateTimeout(options.timeoutMs ?? 30_000),
    }
}
