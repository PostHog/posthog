import { join } from 'node:path'
import { z } from 'zod'

import { TYPESCRIPT_SDKS, type LoadedConfig, type TypeScriptSdk } from '@/core/config'
import type { Context } from '@/core/context'
import { HogError } from '@/core/errors'
import { absolutePath } from '@/core/paths'

export const LANGUAGES = ['typescript', 'golang', 'python'] as const
export type Language = (typeof LANGUAGES)[number]

interface LanguageInfo {
    name: string
    // Python modules can't have hyphens in their names.
    defaultFile: string
    nextSteps: (file: string) => string[]
}

export const LANGUAGE_INFO: Record<Language, LanguageInfo> = {
    typescript: {
        name: 'TypeScript',
        defaultFile: 'posthog-typed.ts',
        nextSteps: (file) => [
            `Import PostHog from the generated module: import posthog from './${file}'`,
            "Known events get autocomplete and type checks: posthog.capture('event_name', { property: 'value' })",
            "captureRaw() skips the type checks: posthog.captureRaw('dynamic_event_name', { whatever: 'data' })",
        ],
    },
    golang: {
        name: 'Go',
        defaultFile: 'posthog-typed.go',
        nextSteps: (file) => [
            'Install the PostHog Go SDK if you have not yet: go get github.com/posthog/posthog-go',
            `Move ${file} into a folder named typed, or change the package line at the top of the file`,
            'Capture typed events: client.Enqueue(typed.EventNameCapture("user_id", requiredProp))',
        ],
    },
    python: {
        name: 'Python',
        defaultFile: 'posthog_typed.py',
        nextSteps: (file) => [
            `Import the typed client from ${file}: from posthog_typed import PosthogTyped`,
            'Create it like the PostHog client: client = PosthogTyped("<project token>", host="<host>")',
            'Capture typed events: client.capture_event_name(required_property="value", distinct_id="user_123")',
        ],
    },
}

export const DEFAULT_TYPESCRIPT_SDK: TypeScriptSdk = 'posthog-js'

const TYPES_ONLY_INFO: LanguageInfo = {
    name: 'TypeScript (types only)',
    defaultFile: 'posthog-events.ts',
    nextSteps: (file) => [
        `Import the event types, with no SDK dependency: import type { EventName, EventProperties } from './${file}'`,
        'Use them to type the calls to any PostHog SDK, such as posthog-react-native: function track<K extends EventName>(event: K, properties: EventProperties<K>) { posthog.capture(event, properties) }',
    ],
}

export function moduleInfo(language: Language, sdk: TypeScriptSdk | undefined): LanguageInfo {
    return language === 'typescript' && sdk === 'none' ? TYPES_ONLY_INFO : LANGUAGE_INFO[language]
}

export function isLanguage(value: string): value is Language {
    return (LANGUAGES as readonly string[]).includes(value)
}

const Definitions = z.object({
    content: z.string(),
    event_count: z.number(),
    schema_hash: z.string(),
    sdk: z.enum(TYPESCRIPT_SDKS).optional(),
})

export type Definitions = z.infer<typeof Definitions>

export async function fetchDefinitions(
    ctx: Context,
    language: Language,
    sdk: TypeScriptSdk | undefined
): Promise<Definitions> {
    const typesOnly = language === 'typescript' && sdk === 'none'
    const query = new URLSearchParams(typesOnly ? { sdk: 'none' } : {})
    const path = query.size > 0 ? `event_definitions/${language}/?${query}` : `event_definitions/${language}/`
    const definitions = await (await ctx.posthog()).get(path, Definitions)
    // A PostHog that predates `sdk` ignores the query and sends the posthog-js module, without saying which SDK.
    if (typesOnly && definitions.sdk !== 'none') {
        throw new HogError(
            'sdk_unsupported',
            'This PostHog instance cannot generate TypeScript types without an SDK yet.',
            'Update PostHog, or pull without --sdk none.'
        )
    }
    return definitions
}

// posthog.json stores paths relative to its own folder. A new file goes in the working folder.
export function configRoot(ctx: Context, loaded: LoadedConfig | undefined): string {
    return loaded?.root ?? ctx.runtime.cwd()
}

// Resolves a path the caller typed. A folder, or a path that ends with a slash, gets the
// language's default file name.
export async function chosenFile(
    ctx: Context,
    path: string,
    language: Language,
    sdk: TypeScriptSdk | undefined
): Promise<string> {
    const absolute = absolutePath(ctx.runtime.cwd(), path)
    const asFolder = /[\\/]$/.test(path) || (await ctx.runtime.isDirectory(absolute))
    return asFolder ? join(absolute, moduleInfo(language, sdk).defaultFile) : absolute
}
