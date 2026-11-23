import { resolve } from 'node:path'
import { z } from 'zod'

import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { findGitRoot } from '@/core/paths'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { HostSchema } from '@/posthog/host'

const STACK_NAME = /^[a-z0-9][a-z0-9_-]*$/

export const StackName = z.string().regex(STACK_NAME, {
    error: 'Use lowercase letters, numbers, underscores or hyphens, starting with a letter or number.',
})

const parseName = (raw: string, failure: ParseFailure): string =>
    parseOrThrow(StackName, raw, { ...failure, hint: 'Use a name from posthog.json.' })

export const stackOptions = {
    stack: { type: 'string', placeholder: 'name', description: 'The stack name in posthog.json', parse: parseName },
    env: { type: 'string', placeholder: 'name', description: 'The environment name in the stack', parse: parseName },
} as const

// Without a `stacks` entry, a folder has one stack in `.ph/`.
export const DEFAULT_STACK_DIR = '.ph'

const StackEnvironment = z
    .strictObject({
        host: HostSchema.meta({ format: 'uri' }).describe('The PostHog host, like https://us.posthog.com.'),
        project: z.int().positive().describe('The project ID, like the 2 in https://us.posthog.com/project/2.'),
    })
    .describe('Where one environment of the stack lives.')

const Stack = z
    .strictObject({
        dir: z
            .string()
            .min(1)
            .describe('The stack folder, relative to posthog.json. Its index.ts exports the definitions.'),
        environments: z
            .record(StackName, StackEnvironment)
            .optional()
            .describe('The projects this stack is pushed to, by environment name, like production.'),
    })
    .describe('One stack: a folder of definitions that PostHog manages in code.')

export const StacksConfig = z
    .record(StackName, Stack)
    .describe('The stacks managed in code, by name. Without it, the stack is the .ph/ folder next to posthog.json.')

export type StacksConfig = z.infer<typeof StacksConfig>

export interface ResolvedStack {
    env?: string
    environment?: z.output<typeof StackEnvironment>
    // Undefined for the default stack, which `hog init` names.
    name: string | undefined
    // As written in posthog.json, relative to its folder.
    dir: string
    path: string
    configRoot: string
    root: string
}

export async function resolveStack(ctx: Context, requested?: string, requestedEnv?: string): Promise<ResolvedStack> {
    const [loaded, repo] = await Promise.all([ctx.config(), findGitRoot(ctx.runtime)])
    const root = repo?.root ?? loaded?.root ?? ctx.runtime.cwd()
    const configRoot = loaded?.root ?? root
    const stacks = loaded?.config.stacks
    if (!stacks || Object.keys(stacks).length === 0) {
        if (requested !== undefined) {
            throw new HogError(
                'stack_unknown',
                `posthog.json has no stack named ${requested}.`,
                'Add it under `stacks` in posthog.json, or run the command without --stack.',
                EXIT_USAGE
            )
        }
        if (requestedEnv !== undefined) {
            throw unknownEnv(requestedEnv)
        }
        return {
            name: undefined,
            dir: DEFAULT_STACK_DIR,
            path: resolve(configRoot, DEFAULT_STACK_DIR),
            configRoot,
            root,
        }
    }
    const names = Object.keys(stacks).sort()
    const name = requested ?? (names.length === 1 ? names[0] : undefined)
    if (name === undefined) {
        throw new HogError(
            'stack_required',
            `posthog.json has ${names.length} stacks, so the command needs one named.`,
            `Pass --stack with one of: ${names.join(', ')}.`,
            EXIT_USAGE
        )
    }
    const stack = Object.hasOwn(stacks, name) ? stacks[name] : undefined
    if (!stack) {
        throw new HogError(
            'stack_unknown',
            `posthog.json has no stack named ${name}.`,
            `Pass --stack with one of: ${names.join(', ')}.`,
            EXIT_USAGE
        )
    }
    const environments = stack.environments ?? {}
    const envNames = Object.keys(environments).sort()
    if (requestedEnv === undefined && envNames.length > 1) {
        throw new HogError(
            'environment_required',
            `Stack ${name} has more than one environment.`,
            `Pass --env with one of: ${envNames.join(', ')}.`,
            EXIT_USAGE
        )
    }
    const env = requestedEnv ?? envNames[0]
    if (env !== undefined && !Object.hasOwn(environments, env)) {
        throw unknownEnv(env, envNames)
    }
    return {
        name,
        dir: stack.dir,
        path: resolve(configRoot, stack.dir),
        configRoot,
        root,
        env,
        environment: env === undefined ? undefined : environments[env],
    }
}

function unknownEnv(env: string, names: string[] = []): HogError {
    return new HogError(
        'environment_unknown',
        `This stack has no environment named ${env}.`,
        names.length
            ? `Pass --env with one of: ${names.join(', ')}.`
            : 'Configure environments in posthog.json or omit --env.',
        EXIT_USAGE
    )
}
