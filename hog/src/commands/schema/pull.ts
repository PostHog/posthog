import { defineCommand } from '@/core/command'
import { updateConfig, type SchemaLanguage } from '@/core/config'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { absolutePath, storedPath } from '@/core/paths'
import { plural } from '@/core/text'

import { chosenFile, configRoot, fetchDefinitions, isLanguage, LANGUAGE_INFO, LANGUAGES, type Language } from './shared'

interface PulledLanguage {
    language: Language
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

        const pulled: PulledLanguage[] = []
        const entries: Partial<Record<Language, SchemaLanguage>> = {}
        for (const language of languages) {
            const saved = configured[language]
            let file: string
            if (options.file !== undefined) {
                file = await chosenFile(ctx, options.file, language)
            } else if (saved) {
                file = absolutePath(root, saved.output_path)
            } else {
                const fallback = LANGUAGE_INFO[language].defaultFile
                const answer = ctx.prompts
                    ? await ctx.prompts.text(
                          `Where should hog write the ${LANGUAGE_INFO[language].name} module? Your app imports PostHog from it.`,
                          { initialValue: fallback }
                      )
                    : fallback
                file = await chosenFile(ctx, answer || fallback, language)
            }

            const definitions = await fetchDefinitions(ctx, language)
            const outputPath = storedPath(root, file)
            // The module carries the time PostHog generated it, so only the hash says whether the events changed.
            const unchanged =
                saved?.output_path === outputPath &&
                saved.schema_hash === definitions.schema_hash &&
                (await ctx.runtime.exists(file))
            if (!unchanged && !options.dryRun) {
                await ctx.runtime.writeFile(file, definitions.content)
                entries[language] = {
                    output_path: outputPath,
                    schema_hash: definitions.schema_hash,
                    updated_at: new Date(ctx.runtime.now()).toISOString(),
                    event_count: definitions.event_count,
                }
            }
            pulled.push({
                language,
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
        for (const pulled of result.languages) {
            const { name, nextSteps } = LANGUAGE_INFO[pulled.language]
            const events = plural(pulled.eventCount, 'event')
            if (pulled.status === 'unchanged') {
                out.line(`${out.style('Up to date', 'green', 'bold')}  ${name} in ${pulled.file} (${events})`)
                continue
            }
            if (pulled.status === 'would_write') {
                out.line(`${out.style('Would generate', 'yellow', 'bold')}  ${name} in ${pulled.file} (${events})`)
                continue
            }
            out.line(`${out.style('Generated', 'green', 'bold')}  ${name} in ${pulled.file} (${events})`)
            out.line()
            out.line(out.style('Next steps:', 'bold'))
            nextSteps(pulled.file).forEach((step, index) => out.line(`  ${index + 1}. ${step}`))
            out.line()
        }
        if (result.configUpdated) {
            out.line(out.style(`Saved the settings in ${result.config}`, 'dim'))
        }
        if (result.dryRun) {
            out.line(out.style('Dry run: no files written.', 'dim'))
        }
    },

    agent({ result, out }) {
        out.jsonLines(result.languages)
    },

    telemetry: ({ result }) => ({
        languages: result.languages.map((pulled) => pulled.language),
        written: result.languages.filter((pulled) => pulled.status === 'written').length,
    }),
})
