/**
 * Mounts a `TriggerModule`'s routes behind the guard their declared `auth`
 * implies. This is the single enforcement point: every route — no matter the
 * trigger — runs the same resolve-agent + auth sequence here before its
 * handler sees the request. Forgetting to authenticate is impossible because
 * the handler only runs after the guard for its declared `auth` passes.
 */

import { Request, Response, Router } from 'express'

import { AuthConfig, SLACK_SIGNING_SECRET_KEY, triggerAuthConfig } from '@posthog/agent-shared'

import { authorize, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
import { asyncHandler } from '../routing/http-utils'
import { ResolvedAgent } from '../routing/resolver'
import { hasTrigger, resolveAgent } from './resolve'
import { verifySlackSignature } from './slack-signature'
import type {
    AuthedRouteCtx,
    CustomAuthRouteCtx,
    RouteCtx,
    TriggerDeps,
    TriggerModule,
    TriggerRoute,
    TriggerType,
} from './types'

/** Build an Express router that mounts every route of a module behind its guard. */
export function mountTrigger(deps: TriggerDeps, module: TriggerModule): Router {
    const r = Router({ mergeParams: true })
    for (const route of module.routes) {
        const register = route.method === 'GET' ? r.get.bind(r) : r.post.bind(r)
        register(
            route.path,
            asyncHandler((req: Request, res: Response) => runGuardedRoute(deps, module.type, route, req, res))
        )
    }
    return r
}

function authConfigFor(resolved: ResolvedAgent, type: TriggerType): AuthConfig | null {
    const trigger = resolved.revision.spec.triggers.find((t) => t.type === type)
    return trigger ? triggerAuthConfig(trigger) : null
}

async function runGuardedRoute(
    deps: TriggerDeps,
    type: TriggerType,
    route: TriggerRoute,
    req: Request,
    res: Response
): Promise<void> {
    // Every route resolves the agent first. `resolveAgent` may already have
    // written a 400 (ambiguous prefix) / 401 (preview token) — only fill in
    // the 404 when nothing was sent.
    const resolved = await resolveAgent(deps.resolver, req, res)
    if (!resolved) {
        if (!res.headersSent) {
            res.status(404).json({ error: 'no_agent' })
        }
        return
    }
    const base: RouteCtx = { req, res, deps, resolved, parsed: undefined }

    // Resolve the auth-specific context (or respond + return on failure). The
    // body/query parse happens after this, so a malformed payload never short-
    // circuits the auth gate.
    let ctx: RouteCtx | AuthedRouteCtx | CustomAuthRouteCtx
    switch (route.auth) {
        case 'public': {
            ctx = base
            break
        }
        case 'slack_signing': {
            if (!hasTrigger(resolved, type)) {
                res.status(404).json({ error: `no_${type}_trigger` })
                return
            }
            const signingSecret = await deps.signingSecretResolver.resolve(SLACK_SIGNING_SECRET_KEY, resolved.revision)
            if (!signingSecret) {
                res.status(500).json({ error: 'signing_secret_unresolved' })
                return
            }
            if (!verifySlackSignature(req, signingSecret)) {
                res.status(401).json({ error: 'invalid_signature' })
                return
            }
            ctx = base
            break
        }
        case 'custom': {
            const authConfig = authConfigFor(resolved, type)
            if (!authConfig) {
                res.status(404).json({ error: `no_${type}_trigger` })
                return
            }
            ctx = {
                ...base,
                authConfig,
                authorize: () =>
                    authorize(
                        req,
                        resolved.application,
                        resolved.revision,
                        authConfig,
                        deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
                    ),
            }
            break
        }
        case 'agent_spec': {
            const authConfig = authConfigFor(resolved, type)
            if (!authConfig) {
                res.status(404).json({ error: `no_${type}_trigger` })
                return
            }
            const auth = await authorize(
                req,
                resolved.application,
                resolved.revision,
                authConfig,
                deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
            )
            if (!auth.ok) {
                res.status(auth.status).json({ error: auth.reason })
                return
            }
            ctx = { ...base, authConfig, principal: auth.principal, credentials: auth.credentials }
            break
        }
    }

    // Validate the declared payload schema (body for POST, query for GET) and
    // hand the handler a typed `ctx.parsed`. Centralized here so no handler can
    // skip validation or drift from its declared schema.
    if (route.schema) {
        const source = route.method === 'GET' ? req.query : req.body
        const result = route.schema.safeParse(source)
        if (!result.success) {
            res.status(400).json({ error: 'invalid_body', issues: result.error.issues })
            return
        }
        ctx.parsed = result.data
    }
    await route.handler(ctx as never)
}
