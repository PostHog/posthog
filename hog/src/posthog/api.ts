import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseLosslessJson } from '@/core/json'
import type { RuntimeFetch } from '@/core/runtime'
import { parseOrThrow, type Schema } from '@/core/schema'
import { VERSION } from '@/version'

import { hostUrl } from './host'
import type { KeySession } from './key-session'
import { challengedScopes, isScopeName, stepUpCommand } from './scope-challenge'

export const USER_AGENT = `hog/${VERSION}`
// Generous, because a HogQL query can run for minutes. It only stops a connection that hangs.
const REQUEST_TIMEOUT_MS = 10 * 60 * 1000

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

export interface HttpRequest {
    method: Method
    body?: unknown
    // Sent form encoded instead of `body`, as the OAuth endpoints expect.
    form?: Record<string, string>
    token?: string
    timeoutMs?: number
}

export interface HttpResponse {
    status: number
    ok: boolean
    json: unknown
    text: string
    headers: Headers
}

// Sends one JSON request to PostHog. Any failure before the whole body arrives, including the
// deadline, is a `network_error`, so callers handle a dropped connection in one place.
export async function sendRequest(fetchFn: RuntimeFetch, url: URL, request: HttpRequest): Promise<HttpResponse> {
    const headers: Record<string, string> = {
        'Content-Type': request.form ? 'application/x-www-form-urlencoded' : 'application/json',
        'User-Agent': USER_AGENT,
    }
    if (request.token) {
        headers.Authorization = `Bearer ${request.token}`
    }
    let response: Response
    let text: string
    try {
        response = await fetchFn(url, {
            method: request.method,
            headers,
            body: request.form
                ? new URLSearchParams(request.form).toString()
                : request.body === undefined
                  ? undefined
                  : JSON.stringify(request.body),
            timeoutMs: request.timeoutMs ?? REQUEST_TIMEOUT_MS,
        })
        text = await response.text()
    } catch (error) {
        throw new HogError(
            'network_error',
            `hog couldn't reach ${url.origin}: ${error instanceof Error ? error.message : String(error)}`,
            'Check the host and your network connection.'
        )
    }
    // Callers check `json` against a schema of their own. A body that isn't JSON leaves it undefined.
    const json = text ? parseLosslessJson(text) : undefined
    return { status: response.status, ok: response.ok, json, text, headers: response.headers }
}

// A non-2xx answer from PostHog. `type` is the DRF error type, such as `validation_error`.
export class ApiError extends HogError {
    constructor(
        readonly status: number,
        readonly type: string | undefined,
        code: string,
        message: string,
        hint?: string,
        details?: Readonly<Record<string, unknown>>
    ) {
        super(code, message, hint, undefined, details)
    }

    override withHint(hint: string): ApiError {
        return new ApiError(this.status, this.type, this.code, this.message, hint, this.details)
    }
}

export type StepUp = (scopes: readonly string[]) => Promise<boolean>

// A 403, so callers that treat a missing scope as a missing detail keep working. Agents get the
// scopes and the command as data. Only scope names reach the command, because agents run it.
export function stepUpRequired(
    scopes: readonly string[],
    message = `Your login needs ${scopes.join(', ')} for this.`
): ApiError {
    const named = scopes.filter(isScopeName)
    const command = stepUpCommand(named)
    return new ApiError(
        403,
        undefined,
        'step_up_required',
        message,
        `Run \`${command}\` to add the scopes to your login, then run the command again.`,
        { scopes: named, command }
    )
}

// A DRF error body. `type` is the DRF error type, such as `validation_error`.
// A field of another type reads as missing, so the others still reach the error message.
const DRFErrorBody = z.object({
    type: z.string().optional().catch(undefined),
    code: z.string().optional().catch(undefined),
    detail: z.string().optional().catch(undefined),
})

export class PostHogApi {
    constructor(
        private readonly session: KeySession,
        private readonly fetchFn: RuntimeFetch,
        private readonly stepUp?: StepUp
    ) {}

    // Paths are relative to the project, so `query` is /api/environments/<project id>/query. A path
    // that starts with `/`, like `/api/users/@me/`, is relative to the host instead.
    private url(path: string): URL {
        const { host, projectId } = this.session.current
        // hostUrl keeps the path a self-hosted PostHog can sit under, which `new URL` would drop. A
        // path from a pagination link already starts with it.
        const root = hostUrl(host, '')
        let url: URL
        if (path.startsWith('/')) {
            url = path.startsWith(root.pathname) ? new URL(path, root) : hostUrl(host, path.slice(1))
        } else {
            url = new URL(path, hostUrl(host, `api/environments/${projectId}/`))
        }
        // A path from a link PostHog sent, such as `//other.example/`, must not carry the token elsewhere.
        if (url.origin !== root.origin) {
            throw new HogError('unexpected_response', `PostHog sent a link to another host: ${url.origin}.`)
        }
        return url
    }

    // Each call names the schema of the answer it expects, so a command never works with a shape
    // PostHog didn't send.
    get<T>(path: string, schema: Schema<T>): Promise<T> {
        return this.request('GET', path, schema)
    }

    post<T>(path: string, body: unknown, schema: Schema<T>): Promise<T> {
        return this.request('POST', path, schema, body)
    }

    patch<T>(path: string, body: unknown, schema: Schema<T>): Promise<T> {
        return this.request('PATCH', path, schema, body)
    }

    private async request<T>(method: Method, path: string, schema: Schema<T>, body?: unknown): Promise<T> {
        const url = this.url(path)
        const send = (): Promise<HttpResponse> =>
            this.session.send(
                (token) => sendRequest(this.fetchFn, url, { method, body, token }),
                (answer) => answer.status === 401
            )
        let response = await send()
        let missing = await this.missingScopes(response)
        // PostHog checks scopes before it does any work, so sending the request again is safe for a
        // POST too. It is sent again once, so a step-up that still falls short ends in the error.
        if (missing && (await this.stepUp?.(missing))) {
            response = await send()
            missing = await this.missingScopes(response)
        }
        if (missing) {
            throw stepUpRequired(missing)
        }
        if (response.text && response.json === undefined) {
            throw new HogError(
                'unexpected_response',
                `PostHog answered with HTTP ${response.status} and a body that isn't JSON.`,
                response.status === 404 ? 'Check the host and the project ID.' : undefined
            )
        }
        if (!response.ok) {
            throw this.failure(response.status, response.json)
        }
        return parseOrThrow(schema, response.json, {
            code: 'unexpected_response',
            context: `PostHog's answer to ${method} ${url.pathname} isn't what hog expects.`,
            hint: 'Check that the host runs a recent version of PostHog.',
        })
    }

    // The challenge names every scope the request needs, so the ones the login holds stay out of the step-up.
    // A login that already holds every challenged scope gets the plain 403: adding them again changes nothing.
    private async missingScopes(response: HttpResponse): Promise<string[] | undefined> {
        const challenged =
            response.status === 403 ? challengedScopes(response.headers.get('www-authenticate')) : undefined
        if (!challenged || !this.stepUp) {
            return challenged
        }
        const { scopesNotCovered } = await import('./scopes')
        const missing = scopesNotCovered(this.session.current.status().scopes ?? [], challenged)
        return missing.length > 0 ? missing : undefined
    }

    // For lookups that only add detail, like the user's email: a missing scope fails the lookup
    // without asking the person to add it.
    withoutStepUp(): PostHogApi {
        return new PostHogApi(this.session, this.fetchFn)
    }

    private failure(status: number, body: unknown): ApiError {
        const error = DRFErrorBody.safeParse(body).data ?? {}
        const hints: Record<number, string> = {
            401: 'Check that the personal API key is valid.',
            403: 'Check that the personal API key has access to this project.',
            404: 'Check the host and the project ID.',
        }
        return new ApiError(
            status,
            error.type,
            error.code ?? `http_${status}`,
            error.detail ?? `PostHog answered with HTTP ${status}.`,
            hints[status]
        )
    }
}
