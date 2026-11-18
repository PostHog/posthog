import { createHash } from 'node:crypto'
import { z } from 'zod'

import type { SkillRead } from '@posthog/mcp/src/cli/library-types'

import type { Context } from '@/core/context'
import { withFileLock } from '@/core/file-lock'
import { parseJsonOrUndefined } from '@/core/json'
import { posthogFile } from '@/posthog/credentials'
import { HostSchema } from '@/posthog/host'
import { LOGIN_COMMAND } from '@/posthog/login/flow'

import { ProductIdSchema } from './products'

export const SETUP_NEXT = 'hog setup next'

export const STEP_IDS = [
    'purpose',
    'login',
    'project',
    'agents-md',
    'install',
    'review',
    'verify',
    'products',
    'mcp',
    'connected',
] as const

export type StepId = (typeof STEP_IDS)[number]

const SkillFileSchema = z.object({
    skill: z.string(),
    path: z.string(),
})

export type SkillFile = z.output<typeof SkillFileSchema>

// Only what can't be looked up again. Credentials, posthog.json, the AGENTS.md block and the events
// are checked on every run.
const SetupStateSchema = z.object({
    folder: z.string(),
    // Epoch milliseconds of the answers to the purpose step. The verify step counts events from then.
    startedAt: z.number(),
    reason: z.string(),
    // An id hog doesn't know, from another hog version, drops out instead of failing the file.
    products: z.array(z.string()).transform((ids) => ids.flatMap((id) => ProductIdSchema.safeParse(id).data ?? [])),
    // The host the purpose step picked, so the login goes there before posthog.json names it.
    host: HostSchema,
    // Set when nobody named the host or answered the region, so the login step can offer the other region.
    hostPicked: z.enum(['default', 'last_login']).optional().catch(undefined),
    reads: z.array(SkillFileSchema),
    completed: z.array(z.string()).transform((ids) => ids.filter((id): id is StepId => isStepId(id))),
})

export type SetupState = z.output<typeof SetupStateSchema>

function isStepId(id: string): id is StepId {
    return (STEP_IDS as readonly string[]).includes(id)
}

// Where a setup applies: the folder of the closest posthog.json, or the working folder without one,
// so each app in a monorepo has its own setup.
export interface SetupScope {
    folder: string
    statePath: string
    lockName: string
    // The folder's pending login. It starts with `hog auth login`, so a new login clears it.
    pendingName: string
}

export async function setupScope(ctx: Context): Promise<SetupScope> {
    const loaded = await ctx.config()
    const folder = loaded?.root ?? ctx.runtime.cwd()
    const hash = createHash('sha256').update(folder).digest('hex')

    return {
        folder,
        statePath: posthogFile(ctx.runtime, `setup/${hash}.json`),
        lockName: `setup-${hash.slice(0, 32)}.lock`,
        pendingName: `${LOGIN_COMMAND} setup ${hash.slice(0, 32)}`,
    }
}

// A file that can't be read counts as no setup, so the setup starts over instead of failing.
export async function readState(ctx: Context, scope: SetupScope): Promise<SetupState | undefined> {
    try {
        const state = parseJsonOrUndefined(await ctx.runtime.readFile(scope.statePath), SetupStateSchema)
        return state?.folder === scope.folder ? state : undefined
    } catch {
        return undefined
    }
}

// Reads the file again under a lock, so a `hog skills read` that records a read at the same time keeps it.
export async function updateState(
    ctx: Context,
    scope: SetupScope,
    change: (state: SetupState | undefined) => SetupState | undefined
): Promise<SetupState | undefined> {
    return withFileLock(ctx.runtime, scope.lockName, async () => {
        const updated = change(await readState(ctx, scope))
        if (updated) {
            await ctx.runtime.writePrivateFile(scope.statePath, JSON.stringify(updated, null, 2))
        }
        return updated
    })
}

export function hasRead(state: SetupState, file: SkillFile): boolean {
    return state.reads.some((read) => read.skill === file.skill && read.path === file.path)
}

// Called by `hog skills read`. A read counts only while a setup is running in this folder, and a failure
// to record it never fails the read.
export async function recordSkillReads(ctx: Context, reads: readonly SkillRead[]): Promise<void> {
    // The install gates stand for having read whole files, so a line range or a search doesn't count.
    const files = reads
        .filter((read) => read.source === 'posthog' && (read.readKind === 'skill' || read.readKind === 'file'))
        .map((read) => ({ skill: `posthog:${read.skill}`, path: read.path }))
    if (files.length === 0) {
        return
    }
    try {
        const scope = await setupScope(ctx)
        const newReads = (state: SetupState | undefined): SkillFile[] =>
            !state || state.completed.includes('connected') ? [] : files.filter((file) => !hasRead(state, file))
        // Most reads have nothing to add, so they skip the lock.
        if (newReads(await readState(ctx, scope)).length === 0) {
            return
        }
        await updateState(ctx, scope, (state) => {
            const added = newReads(state)
            return state && added.length > 0 ? { ...state, reads: [...state.reads, ...added] } : undefined
        })
    } catch {
        // Without a home folder or a readable posthog.json there is no setup to record the read in.
    }
}
