import { join } from 'node:path'
import { z } from 'zod'

import {
    GO_SDKS,
    SCHEMA_SDKS,
    TYPESCRIPT_SDKS,
    type GoSdk,
    type LoadedConfig,
    type SchemaSdk,
    type TypeScriptSdk,
} from '@/core/config'
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
        nextSteps: (file) => goNextSteps(file, DEFAULT_GO_SDK),
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
export const DEFAULT_GO_SDK: GoSdk = 'posthog-go'

// Go treats each major from 2 on as its own module, so the generated package imports one of these.
const GO_IMPORT_PATHS: Record<GoSdk, string> = {
    'posthog-go': 'github.com/posthog/posthog-go',
    'posthog-go-v2': 'github.com/posthog/posthog-go/v2',
}

function goNextSteps(file: string, sdk: GoSdk): string[] {
    return [
        `Install the PostHog Go SDK if you have not yet: go get ${GO_IMPORT_PATHS[sdk]}`,
        ...(sdk === DEFAULT_GO_SDK ? ['On posthog-go 2.x, pull with --sdk posthog-go-v2 instead'] : []),
        `Move ${file} into a folder named typed, or change the package line at the top of the file`,
        'Capture typed events: client.Enqueue(typed.EventNameCapture("user_id", requiredProp))',
    ]
}

const LANGUAGE_SDKS: Partial<Record<Language, readonly SchemaSdk[]>> = {
    typescript: TYPESCRIPT_SDKS,
    golang: GO_SDKS,
}

export function sdkLanguage(sdk: SchemaSdk): Language {
    return (GO_SDKS as readonly string[]).includes(sdk) ? 'golang' : 'typescript'
}

// The SDK a language's module is generated for. A value that belongs to another language counts as unset.
// An unset TypeScript module wraps posthog-js, and an unset Go module imports posthog-go 1.x.
export function effectiveSdk(language: Language, sdk: SchemaSdk | undefined): SchemaSdk | undefined {
    const sdks = LANGUAGE_SDKS[language]
    return sdks ? (sdk !== undefined && sdks.includes(sdk) ? sdk : sdks[0]) : undefined
}

const TYPES_ONLY_INFO: LanguageInfo = {
    name: 'TypeScript (types only)',
    defaultFile: 'posthog-events.ts',
    nextSteps: (file) => [
        `Import the event types, with no SDK dependency: import type { EventName, EventProperties } from './${file}'`,
        'Use them to type the calls to any PostHog SDK, such as posthog-react-native: function track<K extends EventName>(event: K, properties: EventProperties<K>) { posthog.capture(event, properties) }',
    ],
}

export function moduleInfo(language: Language, sdk: SchemaSdk | undefined): LanguageInfo {
    if (language === 'typescript' && sdk === 'none') {
        return TYPES_ONLY_INFO
    }
    if (language === 'golang' && sdk === 'posthog-go-v2') {
        return { ...LANGUAGE_INFO.golang, nextSteps: (file) => goNextSteps(file, sdk) }
    }
    return LANGUAGE_INFO[language]
}

export function isLanguage(value: string): value is Language {
    return (LANGUAGES as readonly string[]).includes(value)
}

const Definitions = z.object({
    content: z.string(),
    event_count: z.number(),
    schema_hash: z.string(),
    sdk: z.enum(SCHEMA_SDKS).optional(),
})

export type Definitions = z.infer<typeof Definitions>

// The choices PostHog has to be asked for. Each language's default needs no query, so it also works on a
// PostHog that predates the choice.
const REQUESTED_SDKS: Partial<Record<SchemaSdk, { language: Language; unsupported: [string, string] }>> = {
    none: {
        language: 'typescript',
        unsupported: [
            'This PostHog instance cannot generate TypeScript types without an SDK yet.',
            'Update PostHog, or pull without --sdk none.',
        ],
    },
    'posthog-go-v2': {
        language: 'golang',
        unsupported: [
            'This PostHog instance cannot generate Go for posthog-go 2.x yet.',
            'Update PostHog, or pull with --sdk posthog-go.',
        ],
    },
}

export async function fetchDefinitions(
    ctx: Context,
    language: Language,
    sdk: SchemaSdk | undefined
): Promise<Definitions> {
    const requested = sdk !== undefined && REQUESTED_SDKS[sdk]?.language === language ? sdk : undefined
    const query = new URLSearchParams(requested ? { sdk: requested } : {})
    const path = query.size > 0 ? `event_definitions/${language}/?${query}` : `event_definitions/${language}/`
    const definitions = await (await ctx.posthog()).get(path, Definitions)
    // A PostHog that predates an `sdk` choice ignores the query and sends the default module, without saying which SDK.
    if (requested && definitions.sdk !== requested) {
        throw new HogError('sdk_unsupported', ...REQUESTED_SDKS[requested]!.unsupported)
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
    sdk: SchemaSdk | undefined
): Promise<string> {
    const absolute = absolutePath(ctx.runtime.cwd(), path)
    const asFolder = /[\\/]$/.test(path) || (await ctx.runtime.isDirectory(absolute))
    return asFolder ? join(absolute, moduleInfo(language, sdk).defaultFile) : absolute
}
