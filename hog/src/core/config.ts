import { dirname, join } from 'node:path'
import { z } from 'zod'

import { HogError } from './errors'
import type { Runtime } from './runtime'

export const CONFIG_FILE = 'posthog.json'

// Where editors fetch the schema from. The file is generated from `PostHogConfig` and checked in.
export const SCHEMA_URL = 'https://raw.githubusercontent.com/PostHog/posthog/master/hog/posthog.schema.json'

export const ARTIFACT_KINDS = ['js', 'hermes', 'proguard', 'dsym', 'elf'] as const
export type ArtifactKind = (typeof ARTIFACT_KINDS)[number]

const Source = z
    .strictObject({
        path: z.string().min(1).describe('A folder or file to scan, relative to posthog.json.'),
        kind: z
            .enum(ARTIFACT_KINDS)
            .optional()
            .describe('The artifact type. hog detects it from the files when this is not set.'),
        ignore: z.array(z.string()).optional().describe('Glob patterns of files to skip, relative to `path`.'),
        mapId: z
            .string()
            .min(1)
            .optional()
            .describe('ProGuard only: the map ID your Android build injected into the app.'),
    })
    .describe('A place where the build writes artifacts with symbols, such as bundles and their sourcemaps.')

const ErrorTracking = z
    .strictObject({
        release: z
            .strictObject({
                name: z.string().min(1).optional().describe('The release name, usually the app or service name.'),
                version: z
                    .string()
                    .min(1)
                    .optional()
                    .describe('The release version. hog uses the git commit when this is not set.'),
            })
            .optional()
            .describe('The release every uploaded symbol set belongs to.'),
        sources: z
            .array(Source)
            .optional()
            .describe('What `hog error-tracking inject`, `upload` and `process` scan when no path is passed.'),
    })
    .describe('Settings for `hog error-tracking`.')

export const PostHogConfig = z
    .strictObject({
        $schema: z.string().optional().describe('The JSON schema for this file.'),
        errorTracking: ErrorTracking.optional(),
        languages: z
            .record(z.string(), z.unknown())
            .optional()
            .describe('Typed SDK settings that `posthog-cli exp schema pull` writes. hog leaves them alone.'),
    })
    .describe('Settings for the PostHog CLI. Never put API keys here: use `hog auth login` or environment variables.')

export type PostHogConfig = z.infer<typeof PostHogConfig>

export interface LoadedConfig {
    path: string
    // Relative paths in the file resolve from this folder.
    root: string
    config: PostHogConfig
}

export interface ConfigProblem {
    path: string
    message: string
}

export function configSchema(): Record<string, unknown> {
    return { $id: SCHEMA_URL, ...z.toJSONSchema(PostHogConfig, { target: 'draft-2020-12' }) }
}

export async function findConfig(runtime: Runtime): Promise<string | undefined> {
    let folder = runtime.cwd()
    for (;;) {
        const candidate = join(folder, CONFIG_FILE)
        if (await runtime.exists(candidate)) {
            return candidate
        }
        const parent = dirname(folder)
        if ((await runtime.exists(join(folder, '.git'))) || parent === folder) {
            return undefined
        }
        folder = parent
    }
}

// Returns every problem with the file instead of the first, so `hog config check` can list them all.
export function validateConfig(contents: string): { config?: PostHogConfig; problems: ConfigProblem[] } {
    let raw: unknown
    try {
        raw = JSON.parse(contents)
    } catch (error) {
        return {
            problems: [{ path: '', message: `Not valid JSON: ${error instanceof Error ? error.message : error}` }],
        }
    }
    const parsed = PostHogConfig.safeParse(raw)
    if (parsed.success) {
        return { config: parsed.data, problems: [] }
    }
    return {
        problems: parsed.error.issues.map((issue) => ({
            path: issue.path
                .map((part) => (typeof part === 'number' ? `[${part}]` : `.${String(part)}`))
                .join('')
                .replace(/^\./, ''),
            message: issue.message,
        })),
    }
}

export async function loadConfig(runtime: Runtime): Promise<LoadedConfig | undefined> {
    const path = await findConfig(runtime)
    if (path === undefined) {
        return undefined
    }
    const { config, problems } = validateConfig(await runtime.readFile(path))
    if (!config) {
        const [first] = problems
        throw new HogError(
            'invalid_config',
            `${path} is not valid: ${first?.path ? `${first.path}: ` : ''}${first?.message ?? 'unknown problem'}`,
            'Run `hog config check` to see every problem.'
        )
    }
    return { path, root: dirname(path), config }
}
