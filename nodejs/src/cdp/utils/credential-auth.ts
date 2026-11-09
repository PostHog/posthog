import { Counter } from 'prom-client'

import { buildIntegerMatcher } from '~/common/config/matchers'
import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

// Mirrors AuthDeclarationSchemaSerializer in products/cdp/backend/validation.py.
export type CredentialAuthDeclaration = {
    scheme: 'bearer' | 'header' | 'basic' | 'query' | 'body'
    name?: string
    prefix?: string
    path?: string
    opt_in?: boolean
    username_input?: string
    username_field?: string
    password_field?: string
    field?: string
    origins?: string[]
    origin_input?: string
}

export type ResolvedCredential = {
    inputKey: string
    declaration: CredentialAuthDeclaration
    origins: string[]
    secret: string
    username?: string
}

export type CredentialRequest = { url: string; headers: Record<string, string>; body: string | undefined }

export type CredentialOutcome =
    | { ok: true; request: CredentialRequest }
    | { ok: false; error: string; request?: undefined }

// The value code sees for an input whose credential the worker applies. It names the input and holds no secret.
export const CREDENTIAL_HANDLE_KEY = '$credential'

export const credentialHandle = (inputKey: string): Record<string, string> => ({ [CREDENTIAL_HANDLE_KEY]: inputKey })

export function credentialHandleInputKey(value: unknown): string | null {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) {
        return null
    }
    const key = (value as Record<string, unknown>)[CREDENTIAL_HANDLE_KEY]
    return typeof key === 'string' ? key : null
}

type IntegrationAuthRule = {
    declaration: CredentialAuthDeclaration
    origins: (config: Record<string, unknown>) => string[]
}

// A connection's origins and placement come from its kind, never from the function, because anyone who can edit the
// function can also edit its input schema. A kind is listed once a template that uses it moves to `auth`.
export const INTEGRATION_AUTH: Record<string, IntegrationAuthRule> = {
    slack: { declaration: { scheme: 'bearer' }, origins: () => ['https://slack.com'] },
}

// Fields a connection resolves to code in handle mode: its config, without anything that can hold a credential.
const CREDENTIAL_CONFIG_FIELDS = new Set(['access_token', 'access_token_raw', 'refresh_token', 'id_token'])

export function publicIntegrationConfig(
    config: Record<string, unknown> | null | undefined,
    sensitiveConfig: Record<string, unknown> | null | undefined
): Record<string, unknown> {
    return Object.fromEntries(
        Object.entries(config ?? {}).filter(
            ([name]) => !CREDENTIAL_CONFIG_FIELDS.has(name) && !Object.hasOwn(sensitiveConfig ?? {}, name)
        )
    )
}

// Must produce the origins that `url_origin` in products/cdp/backend/credential_auth.py stores.
export function requestOrigin(url: string): string | null {
    let parsed: URL
    try {
        parsed = new URL(url)
    } catch {
        return null
    }
    // A loop and not /\.+$/, because that regex backtracks in quadratic time on a long run of dots.
    let end = parsed.hostname.length
    while (end > 0 && parsed.hostname[end - 1] === '.') {
        end--
    }
    const port = parsed.port ? `:${parsed.port}` : ''
    return `${parsed.protocol}//${parsed.hostname.slice(0, end)}${port}`
}

// Headers the HTTP client reads as the request authority. Undici takes the TLS server name and the HTTP/2 `:authority`
// from `host`, so a request can reach a host other than the one in its URL on a server that routes by either.
const AUTHORITY_HEADERS = new Set(['host', ':authority'])

function routedOrigins(request: CredentialRequest): string[] | null {
    const urlOrigin = requestOrigin(request.url)
    if (!urlOrigin) {
        return null
    }
    const protocol = new URL(request.url).protocol
    const overrides = Object.entries(request.headers)
        .filter(([name]) => AUTHORITY_HEADERS.has(name.toLowerCase()))
        .map(([, value]) => authorityOrigin(protocol, value))
    return [urlOrigin, ...overrides]
}

function authorityOrigin(protocol: string, authority: string): string {
    const value = authority.trim()
    // The URL parser reads a host out of userinfo, a path or a fragment, but the server reads the whole value. Such a
    // value keeps its raw form, which no bound origin can equal.
    const parsed = /[/?#@\\\s]/.test(value) ? null : requestOrigin(`${protocol}//${value}`)
    return parsed ?? `${protocol}//${value.toLowerCase()}`
}

function withHeader(headers: Record<string, string>, name: string, value: string): Record<string, string> {
    const lowered = name.toLowerCase()
    const kept = Object.entries(headers).filter(([existing]) => existing.toLowerCase() !== lowered)
    return { ...Object.fromEntries(kept), [name]: value }
}

function withBodyPath(body: string | undefined, path: string, value: string): string | null {
    let parsed: unknown
    try {
        parsed = parseJSON(body ?? '{}')
    } catch {
        return null
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return null
    }
    const parts = path.split('.')
    let target = parsed as Record<string, unknown>
    for (const part of parts.slice(0, -1)) {
        const next = Object.hasOwn(target, part) ? target[part] : undefined
        if (typeof next !== 'object' || next === null || Array.isArray(next)) {
            target[part] = {}
        }
        target = target[part] as Record<string, unknown>
    }
    target[parts[parts.length - 1]] = value
    return JSON.stringify(parsed)
}

// Code may set the same header, parameter or body key, so the worker overwrites it rather than add a second one.
export function applyCredential(request: CredentialRequest, credential: ResolvedCredential): CredentialOutcome {
    const { declaration, secret } = credential
    switch (declaration.scheme) {
        case 'bearer':
            return {
                ok: true,
                request: { ...request, headers: withHeader(request.headers, 'Authorization', `Bearer ${secret}`) },
            }
        case 'header':
            return {
                ok: true,
                request: {
                    ...request,
                    headers: withHeader(request.headers, declaration.name!, `${declaration.prefix ?? ''}${secret}`),
                },
            }
        case 'basic': {
            const encoded = Buffer.from(`${credential.username ?? ''}:${secret}`).toString('base64')
            return {
                ok: true,
                request: { ...request, headers: withHeader(request.headers, 'Authorization', `Basic ${encoded}`) },
            }
        }
        case 'query': {
            const url = new URL(request.url)
            url.searchParams.set(declaration.name!, secret)
            return { ok: true, request: { ...request, url: url.toString() } }
        }
        case 'body': {
            const body = withBodyPath(request.body, declaration.path!, secret)
            if (body === null) {
                return { ok: false, error: 'The request body must be a JSON object to carry this credential.' }
            }
            return { ok: true, request: { ...request, body } }
        }
    }
}

type Mode = 'observe' | 'enforce'

export const credentialAuthCounter = new Counter({
    name: 'cdp_credential_auth_total',
    help: 'Fetches that pass a credential handle, by whether every origin the request routes to is bound to the credential.',
    labelNames: ['outcome', 'mode'],
})

/**
 * Applies a credential to a request whose origin it is bound to. An observed team still sends a mismatched request
 * with the credential, so a binding that misses an origin shows in the metric before enforcement breaks a delivery.
 */
export class CredentialInjector {
    private readonly enforcedForTeam: (teamId: number) => boolean

    constructor(enforceTeams: string) {
        this.enforcedForTeam = buildIntegerMatcher(enforceTeams.trim(), true)
    }

    apply(
        teamId: number,
        functionId: string,
        request: CredentialRequest,
        credential: ResolvedCredential
    ): CredentialOutcome {
        const mode: Mode = this.enforcedForTeam(teamId) ? 'enforce' : 'observe'
        const origins = routedOrigins(request)
        const foreign = origins === null ? [] : origins.filter((origin) => !credential.origins.includes(origin))
        const allowed = origins !== null && foreign.length === 0
        credentialAuthCounter.inc({ outcome: allowed ? 'allowed' : 'mismatch', mode })

        if (!allowed) {
            logger.warn('🦔', '[HogExecutor] Credential sent to an origin it is not bound to', {
                teamId,
                functionId,
                inputKey: credential.inputKey,
                mode,
            })
            if (mode === 'enforce' || origins === null) {
                return {
                    ok: false,
                    error: `Refused to send the credential in input ${credential.inputKey}, because the request goes to an address it can't be sent to. It can be sent to ${credential.origins.join(', ') || 'no address'}.`,
                }
            }
        }
        return applyCredential(request, credential)
    }
}
