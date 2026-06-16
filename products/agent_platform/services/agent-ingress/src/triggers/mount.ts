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
import type { RouteCtx, TriggerDeps, TriggerModule, TriggerRoute, TriggerType } from './types'

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
    const base: RouteCtx = { req, res, deps, resolved }

    switch (route.auth) {
        case 'public': {
            await route.handler(base)
            return
        }
        case 'slack_signing': {
            if (!hasTrigger(resolved, type)) {
                res.status(404).json({ error: `no_${type}_trigger` })
                return
            }
            const signingSecret = await deps.signingSecretResolver.resolve(
                SLACK_SIGNING_SECRET_KEY,
                resolved.application
            )
            if (!signingSecret) {
                res.status(500).json({ error: 'signing_secret_unresolved' })
                return
            }
            if (!verifySlackSignature(req, signingSecret)) {
                res.status(401).json({ error: 'invalid_signature' })
                return
            }
            await route.handler(base)
            return
        }
        case 'custom': {
            const authConfig = authConfigFor(resolved, type)
            if (!authConfig) {
                res.status(404).json({ error: `no_${type}_trigger` })
                return
            }
            await route.handler({
                ...base,
                authConfig,
                authorize: () =>
                    authorize(req, resolved.application, authConfig, deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER),
            })
            return
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
                authConfig,
                deps.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
            )
            if (!auth.ok) {
                res.status(auth.status).json({ error: auth.reason })
                return
            }
            await route.handler({ ...base, authConfig, principal: auth.principal, credentials: auth.credentials })
            return
        }
    }
}
