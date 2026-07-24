// Lazy project/organization id resolution. When the caller doesn't configure a
// project or organization id, resolve it once from `GET /api/users/@me/` and
// cache it for the client's lifetime.

import { type RequestOptions } from './config'
import { MissingOrganizationError, MissingProjectError } from './errors'
import { type HttpClient } from './http'

interface MeResponse {
    team?: { id?: number | string | null } | null
    organization?: { id?: string | null } | null
}

export class ScopeResolver {
    private readonly http: HttpClient
    private configuredProjectId: string | undefined
    private configuredOrganizationId: string | undefined
    private mePromise: Promise<MeResponse> | undefined

    constructor(
        http: HttpClient,
        configured: { projectId?: string | number | undefined; organizationId?: string | undefined }
    ) {
        this.http = http
        this.configuredProjectId = configured.projectId !== undefined ? String(configured.projectId) : undefined
        this.configuredOrganizationId = configured.organizationId
    }

    /** Resolve the project id: per-call override → configured → `GET /api/users/@me/`. */
    async projectId(opts?: RequestOptions): Promise<string> {
        if (opts?.projectId !== undefined) {
            return String(opts.projectId)
        }
        if (this.configuredProjectId !== undefined) {
            return this.configuredProjectId
        }
        const me = await this.fetchMe()
        const id = me.team?.id
        if (id === undefined || id === null) {
            throw new MissingProjectError('the API user has no current project')
        }
        this.configuredProjectId = String(id)
        return this.configuredProjectId
    }

    /** Resolve the organization id: per-call override → configured → `GET /api/users/@me/`. */
    async organizationId(opts?: RequestOptions): Promise<string> {
        if (opts?.organizationId !== undefined) {
            return String(opts.organizationId)
        }
        if (this.configuredOrganizationId !== undefined) {
            return this.configuredOrganizationId
        }
        const me = await this.fetchMe()
        const id = me.organization?.id
        if (id === undefined || id === null) {
            throw new MissingOrganizationError('the API user has no current organization')
        }
        this.configuredOrganizationId = String(id)
        return this.configuredOrganizationId
    }

    private fetchMe(): Promise<MeResponse> {
        // Cache the in-flight promise so concurrent first calls share one request.
        this.mePromise ??= this.http.request<MeResponse>({ method: 'GET', path: '/api/users/@me/' })
        return this.mePromise
    }
}
