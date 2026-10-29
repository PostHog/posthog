import { join } from 'node:path'

import type { LoadedConfig } from '@/core/config'
import type { Context } from '@/core/context'
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

export function isLanguage(value: string): value is Language {
    return (LANGUAGES as readonly string[]).includes(value)
}

export interface Definitions {
    content: string
    event_count: number
    schema_hash: string
}

export function fetchDefinitions(ctx: Context, language: Language): Promise<Definitions> {
    return ctx.posthog().then((api) => api.get<Definitions>(`event_definitions/${language}/`))
}

// posthog.json stores paths relative to its own folder. A new file goes in the working folder.
export function configRoot(ctx: Context, loaded: LoadedConfig | undefined): string {
    return loaded?.root ?? ctx.runtime.cwd()
}

// Resolves a path the caller typed. A folder, or a path that ends with a slash, gets the
// language's default file name.
export async function chosenFile(ctx: Context, path: string, language: Language): Promise<string> {
    const absolute = absolutePath(ctx.runtime.cwd(), path)
    const asFolder = /[\\/]$/.test(path) || (await ctx.runtime.isDirectory(absolute))
    return asFolder ? join(absolute, LANGUAGE_INFO[language].defaultFile) : absolute
}
