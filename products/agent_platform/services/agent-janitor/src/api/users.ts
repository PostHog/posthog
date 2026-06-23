/**
 * Agent end-users + their linked identities HTTP surface. Django (via
 * `janitor_client.py` + `AgentApplicationViewSet`) proxies the console "Users"
 * pane through these endpoints. Backed by `PgIdentityAdminStore` — a keyless,
 * metadata-only view over `agent_user` ⋈ `agent_identity_credential`. No
 * credential material is ever read or returned here; the janitor holds no
 * decryption key by design.
 *
 * Routes are scoped at `/users/team/:team_id/agent/:application_id/...`. The
 * janitor never resolves slugs; Django maps slug → application_id first. Same
 * `mount*Routes(app, opts)` shape as `api/memory.ts`.
 */

import { Express, Request, Response } from 'express'
import { z } from 'zod'

import { Logger, PgIdentityAdminStore } from '@posthog/agent-shared'

import { asyncHandler } from '../http-utils'

const ScopeParamsSchema = z.object({
    team_id: z.coerce.number().int().positive('missing_team_id'),
    application_id: z.string().uuid('application_id must be a UUID'),
})

const ConnectionParamsSchema = z.object({
    agent_user_id: z.string().uuid('agent_user_id must be a UUID'),
    provider: z.string().min(1, 'missing_provider'),
})

export interface MountUsersRoutesOpts {
    /** When omitted, every /users/* route returns 503. */
    identityAdmin?: PgIdentityAdminStore
    log: Logger
}

export function mountUsersRoutes(app: Express, opts: MountUsersRoutesOpts): void {
    function scope(req: Request): { teamId: number; applicationId: string } {
        const { team_id, application_id } = ScopeParamsSchema.parse(req.params)
        return { teamId: team_id, applicationId: application_id }
    }

    function needStore(res: Response): PgIdentityAdminStore | null {
        if (!opts.identityAdmin) {
            res.status(503).json({ error: 'identity_admin_not_configured' })
            return null
        }
        return opts.identityAdmin
    }

    /** GET — every end-user for (team, app), each with its linked connections. */
    app.get(
        '/users/team/:team_id/agent/:application_id',
        asyncHandler(async (req, res) => {
            const store = needStore(res)
            if (!store) {
                return
            }
            const { teamId, applicationId } = scope(req)
            const results = await store.listUsersWithConnections(teamId, applicationId)
            res.json({ count: results.length, results })
        })
    )

    /** DELETE — revoke one linked connection (kept for audit, not hard-deleted). */
    app.delete(
        '/users/team/:team_id/agent/:application_id/user/:agent_user_id/connections/:provider',
        asyncHandler(async (req, res) => {
            const store = needStore(res)
            if (!store) {
                return
            }
            const { teamId, applicationId } = scope(req)
            const { agent_user_id, provider } = ConnectionParamsSchema.parse(req.params)
            const revoked = await store.revokeConnection(teamId, applicationId, agent_user_id, provider)
            res.json({ provider, revoked })
        })
    )
}
