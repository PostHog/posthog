import { defineCommand } from '@/core/command'
import { TYPESCRIPT_SDKS, updateConfig, type SchemaLanguage, type TypeScriptSdk } from '@/core/config'
import type { Context } from '@/core/context'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { absolutePath, storedPath } from '@/core/paths'
import { plural } from '@/core/text'

import {
    chosenFile,
    configRoot,
    DEFAULT_TYPESCRIPT_SDK,
    fetchDefinitions,
    isLanguage,
    LANGUAGE_INFO,
    LANGUAGES,
    moduleInfo,
    type Language,
} from './shared'

interface PulledLanguage {
    language: Language
    sdk: TypeScriptSdk | undefined
    file: string
    status: 'written' | 'would_write' | 'unchanged'
    eventCount: number
    schemaHash: string
}

export default defineCommand({
    description: 'Generate a typed PostHog SDK from your event definitions',
    writes: true,
    options: {
        language: {
            type: 'string',
            short: 'l',
            choices: LANGUAGES,
            description: 'The language to generate. Without it, hog regenerates every language in posthog.json',
        },
        sdk: {
            type: 'string',
            choices: TYPESCRIPT_SDKS,
            description:
                'TypeScript only: the SDK the module wraps. none generates only the event types, for posthog-react-native, posthog-node or any other SDK. posthog.json remembers it',
        },
        file: {
            type: 'string',
            placeholder: 'path',
            description: 'Where to write the module. posthog.json remembers it for the next run',
        },
        dryRun: {
            type: 'boolean',
            description: 'Fetch the event definitions and show what would change, without writing',
        },
    },
    scopes: ['event_definition:read'],
    notes: 'hog writes the module only when the event definitions changed or the file is missing, and records the language, path and schema hash in posthog.json. posthog-cli reads the same entries.',
    examples: [
        'hog schema pull --language typescript --file src/lib/',
        'hog schema pull',
        'hog schema pull -l python --file app/posthog_typed.py',
        'hog schema pull -l typescript --sdk none',
    ],

    async run({ options, ctx }) {
        const loaded = await ctx.config()
        const configured = loaded?.config.languages ?? {}
        const root = configRoot(ctx, loaded)

        let languages: Language[]
        if (options.language) {
            languages = [options.language]
        } else if (Object.keys(configured).length > 0) {
            languages = Object.keys(configured).filter(isLanguage)
        } else if (ctx.prompts) {
            languages = [
                await ctx.prompts.select(
                    'Which language should hog generate?',
                    LANGUAGES.map((value) => ({ value, label: LANGUAGE_INFO[value].name }))
                ),
            ]
        } else {
            throw new HogError(
                'language_required',
                'posthog.json has no languages yet, so hog needs to know which one to generate.',
                `Pass --language ${LANGUAGES.join(', --language ')}.`,
                EXIT_USAGE
            )
        }
        if (options.file !== undefined && languages.length !== 1) {
            throw new HogError(
                'usage_error',
                '--file names one module, but hog is generating several languages.',
                'Pass --language too.',
                EXIT_USAGE
            )
        }

        if (options.sdk !== undefined && !languages.includes('typescript')) {
            throw new HogError(
                'usage_error',
                '--sdk only applies to TypeScript, but hog is not generating TypeScript.',
                'Pass --language typescript too.',
                EXIT_USAGE
            )
        }

        const pulled: PulledLanguage[] = []
        const entries: Partial<Record<Language, SchemaLanguage>> = {}
        for (const language of languages) {
            const saved = configured[language]
            const sdk = language === 'typescript' ? await typescriptSdk(ctx, options.sdk, saved) : undefined
            let file: string
            if (options.file !== undefined) {
                file = await chosenFile(ctx, options.file, language, sdk)
            } else if (saved) {
                file = absolutePath(root, saved.output_path)
            } else {
                const info = moduleInfo(language, sdk)
                const answer = ctx.prompts
                    ? await ctx.prompts.text(`Where should hog write the ${info.name} module?`, {
                          initialValue: info.defaultFile,
                      })
                    : info.defaultFile
                file = await chosenFile(ctx, answer || info.defaultFile, language, sdk)
            }

            const definitions = await fetchDefinitions(ctx, language, sdk)
            const outputPath = storedPath(root, file)
            // The module carries the time PostHog generated it, so only the hash says whether the events changed.
            const unchanged =
                saved?.output_path === outputPath &&
                savedSdk(language, saved) === sdk &&
                saved.schema_hash === definitions.schema_hash &&
                (await ctx.runtime.exists(file))
            if (!unchanged && !options.dryRun) {
                await ctx.runtime.writeFile(file, definitions.content)
                entries[language] = {
                    output_path: outputPath,
                    sdk,
                    schema_hash: definitions.schema_hash,
                    updated_at: new Date(ctx.runtime.now()).toISOString(),
                    event_count: definitions.event_count,
                }
            }
            pulled.push({
                language,
                sdk,
                file: outputPath,
                status: unchanged ? 'unchanged' : options.dryRun ? 'would_write' : 'written',
                eventCount: definitions.event_count,
                schemaHash: definitions.schema_hash,
            })
        }

        const dryRun = options.dryRun === true
        if (Object.keys(entries).length === 0) {
            return { config: loaded?.path ?? null, configUpdated: false, dryRun, languages: pulled }
        }
        const config = await updateConfig(ctx.runtime, loaded, (raw) => {
            raw.languages = { ...(raw.languages as object | undefined), ...entries }
        })
        return { config: storedPath(ctx.runtime.cwd(), config), configUpdated: true, dryRun, languages: pulled }
    },

    human({ result, out }) {
        const labels = { unchanged: 'Up to date', would_write: 'Would generate', written: 'Generated' }
        const written = result.languages.filter((pulled) => pulled.status === 'written')
        const effects = result.languages.map(({ language, sdk, file, status, eventCount }) => {
            const label = out.style(labels[status], status === 'would_write' ? 'yellow' : 'green', 'bold')
            return `${label}  ${moduleInfo(language, sdk).name} in ${file} (${plural(eventCount, 'event')})`
        })
        if (result.configUpdated) {
            effects.push(`Saved the settings in ${result.config}`)
        }
        const notes = written.flatMap(({ language, sdk, file }, index) => {
            const { name, nextSteps } = moduleInfo(language, sdk)
            return [
                ...(index > 0 ? [''] : []),
                out.style(written.length > 1 ? `Next steps for ${name}:` : 'Next steps:', 'bold'),
                ...nextSteps(file).map((step, number) => `  ${number + 1}. ${step}`),
            ]
        })

        out.report({
            status: written.length > 0 ? 'done' : 'unchanged',
            result: result.dryRun
                ? 'Dry run: no files written'
                : written.length > 0
                  ? `Generated ${plural(written.length, 'typed SDK')}`
                  : `${plural(result.languages.length, 'typed SDK')} already up to date`,
            effects,
            notes,
        })
    },

    agent({ result, out }) {
        out.jsonLines(result.languages)
    },

    telemetry: ({ result }) => ({
        languages: result.languages.map((pulled) => pulled.language),
        sdks: result.languages.flatMap((pulled) => (pulled.sdk ? [pulled.sdk] : [])),
        written: result.languages.filter((pulled) => pulled.status === 'written').length,
    }),
})

// A posthog.json entry without `sdk` has a module that wraps posthog-js.
function savedSdk(language: Language, saved: SchemaLanguage | undefined): TypeScriptSdk | undefined {
    return language === 'typescript' ? (saved?.sdk ?? DEFAULT_TYPESCRIPT_SDK) : undefined
}

async function typescriptSdk(
    ctx: Context,
    flag: TypeScriptSdk | undefined,
    saved: SchemaLanguage | undefined
): Promise<TypeScriptSdk> {
    if (flag) {
        return flag
    }
    if (saved || !ctx.prompts) {
        return savedSdk('typescript', saved) ?? DEFAULT_TYPESCRIPT_SDK
    }
    return ctx.prompts.select('Which PostHog SDK does this app use?', [
        { value: 'posthog-js', label: 'posthog-js: hog wraps it so capture() checks your events' },
        { value: 'none', label: 'Another SDK, such as posthog-react-native: hog writes only the event types' },
    ])
}
