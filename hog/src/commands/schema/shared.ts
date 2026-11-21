import { join } from 'node:path'
import { z } from 'zod'

import { GO_SDKS, SCHEMA_SDKS, TYPESCRIPT_SDKS, type GoSdk, type LoadedConfig, type SchemaSdk } from '@/core/config'
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
        nextSteps: (file) => goNextSteps(file, 'posthog-go'),
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

// Go treats each major from 2 on as its own module, so the generated package imports one of these.
const GO_IMPORT_PATHS: Record<GoSdk, string> = {
    'posthog-go': 'github.com/posthog/posthog-go',
    'posthog-go-v2': 'github.com/posthog/posthog-go/v2',
}

function goNextSteps(file: string, sdk: GoSdk): string[] {
    return [
        `Install the PostHog Go SDK if you have not yet: go get ${GO_IMPORT_PATHS[sdk]}`,
        ...(sdk === 'posthog-go' ? ['On posthog-go 2.x, pull with --sdk posthog-go-v2 instead'] : []),
        `Move ${file} into a folder named typed, or change the package line at the top of the file`,
        'Capture typed events: client.Enqueue(typed.EventNameCapture("user_id", requiredProp))',
    ]
}

// What one language lets `--sdk` and the `sdk` entry in posthog.json choose. A language with a new choice
// changes only its own entry.
interface LanguageSdks {
    // The first choice is the default.
    choices: readonly SchemaSdk[]
    // Whether posthog.json names the default. TypeScript always did. Go names an SDK only once one is
    // chosen, so an entry written before the choice existed stays as it is.
    recordsDefault: boolean
    // The error for a PostHog that predates a choice. The default has none: such a PostHog generates it
    // anyway, so hog never asks for it.
    unsupported: Partial<Record<SchemaSdk, [message: string, hint: string]>>
    // The module a choice writes, where it differs from the language's own.
    info: Partial<Record<SchemaSdk, LanguageInfo>>
    // What hog asks when neither a flag nor posthog.json chooses.
    prompt?: { message: string; options: { value: SchemaSdk; label: string }[] }
}

export const LANGUAGE_SDKS: Partial<Record<Language, LanguageSdks>> = {
    typescript: {
        choices: TYPESCRIPT_SDKS,
        recordsDefault: true,
        unsupported: {
            none: [
                'This PostHog instance cannot generate TypeScript types without an SDK yet.',
                'Update PostHog, or pull without --sdk none.',
            ],
        },
        info: {
            none: {
                name: 'TypeScript (types only)',
                defaultFile: 'posthog-events.ts',
                nextSteps: (file) => [
                    `Import the event types, with no SDK dependency: import type { EventName, EventProperties } from './${file}'`,
                    'Use them to type the calls to any PostHog SDK, such as posthog-react-native: function track<K extends EventName>(event: K, properties: EventProperties<K>) { posthog.capture(event, properties) }',
                ],
            },
        },
        prompt: {
            message: 'Which PostHog SDK does this app use?',
            options: [
                { value: 'posthog-js', label: 'posthog-js: hog wraps it so capture() checks your events' },
                { value: 'none', label: 'Another SDK, such as posthog-react-native: hog writes only the event types' },
            ],
        },
    },
    golang: {
        choices: GO_SDKS,
        recordsDefault: false,
        unsupported: {
            'posthog-go-v2': [
                'This PostHog instance cannot generate Go for posthog-go 2.x yet.',
                'Update PostHog, or pull with --sdk posthog-go.',
            ],
        },
        info: {
            'posthog-go-v2': { ...LANGUAGE_INFO.golang, nextSteps: (file) => goNextSteps(file, 'posthog-go-v2') },
        },
    },
}

export function sdkLanguage(sdk: SchemaSdk): Language {
    return LANGUAGES.find((language) => LANGUAGE_SDKS[language]?.choices.includes(sdk)) ?? 'typescript'
}

// The SDK a language's module is generated for. An unset value, or one that belongs to another language,
// counts as the language's default.
export function effectiveSdk(language: Language, sdk: SchemaSdk | undefined): SchemaSdk | undefined {
    const sdks = LANGUAGE_SDKS[language]
    return sdks ? (sdk !== undefined && sdks.choices.includes(sdk) ? sdk : sdks.choices[0]) : undefined
}

export function moduleInfo(language: Language, sdk: SchemaSdk | undefined): LanguageInfo {
    return (sdk !== undefined ? LANGUAGE_SDKS[language]?.info[sdk] : undefined) ?? LANGUAGE_INFO[language]
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

export async function fetchDefinitions(
    ctx: Context,
    language: Language,
    sdk: SchemaSdk | undefined
): Promise<Definitions> {
    // Only a choice that an older PostHog cannot generate goes in the query, so the default still works there.
    const unsupported = sdk !== undefined ? LANGUAGE_SDKS[language]?.unsupported[sdk] : undefined
    const query = new URLSearchParams(sdk !== undefined && unsupported ? { sdk } : {})
    const path = query.size > 0 ? `event_definitions/${language}/?${query}` : `event_definitions/${language}/`
    const definitions = await (await ctx.posthog()).get(path, Definitions)
    // A PostHog that predates the choice ignores the query and sends the default module, without saying which SDK.
    if (unsupported && definitions.sdk !== sdk) {
        throw new HogError('sdk_unsupported', ...unsupported)
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
