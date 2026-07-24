/**
 * Shared scope resolution for the memory + table tools. Both families take an
 * optional `space` arg and resolve it the same way against the agent's spec
 * grants (`ToolContext.memorySpaceGrants`), so the logic lives here once rather
 * than duplicated per tool file. The per-family `access_denied` envelope differs
 * (memory has no `code`, table does), so each file keeps its own tiny `denied`
 * helper and calls `resolveMemoryScope` for the decision.
 */
import { MemoryScope, ToolContext, Type } from '@posthog/agent-shared'

/** The optional `space` arg exposed by every memory + table tool. */
export const SPACE = Type.Optional(
    Type.String({
        description:
            'Use a shared memory space instead of your own private data: the space slug. Works only when your agent is granted access to that space (same team). Reads need a read grant; writes need read_write. Omit to use your own private data.',
    })
)

/**
 * Resolve the storage scope for a memory/table op. `space` targets a shared
 * memory space; it's honoured only when the agent's spec grants access — reads
 * (`needWrite=false`) need any grant, writes need `read_write`. Omitting `space`
 * = the agent's own private scope (always allowed). `teamId` is NEVER taken from
 * an arg, so a grant can only reach spaces in the agent's own team. Returns the
 * scope, or null = access denied (caller maps to its `access_denied` envelope).
 */
export function resolveMemoryScope(ctx: ToolContext, space: string | undefined, needWrite: boolean): MemoryScope | null {
    if (space === undefined) {
        return { teamId: ctx.teamId, applicationId: ctx.applicationId }
    }
    const grant = ctx.memorySpaceGrants?.get(space)
    if (!grant || (needWrite && grant.access !== 'read_write')) {
        return null
    }
    return { teamId: ctx.teamId, applicationId: ctx.applicationId, space }
}
