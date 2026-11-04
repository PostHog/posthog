import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { apiConnection, findTool, grantedScopes, missingScopesError, toHogError } from '@/posthog/api-tools'

function parseInput(text: string | undefined): Record<string, unknown> {
    if (text === undefined) {
        return {}
    }
    let input: unknown
    try {
        input = JSON.parse(text)
    } catch (error) {
        throw new HogError(
            'invalid_json',
            `The input isn't valid JSON: ${(error as Error).message}`,
            'Pass one JSON object, like \'{"limit": 10}\'.',
            EXIT_USAGE
        )
    }
    if (input === null || typeof input !== 'object' || Array.isArray(input)) {
        throw new HogError(
            'invalid_json',
            'The input must be a JSON object.',
            'Pass one JSON object, like \'{"limit": 10}\'.',
            EXIT_USAGE
        )
    }
    return input as Record<string, unknown>
}

export default defineCommand({
    description: 'Call an API tool with JSON input and print its result',
    args: {
        tool: { description: 'The tool name, as `hog api tools` lists it' },
        input: { description: 'The input as a JSON object, or - to read it from stdin', optional: true, stdin: true },
    },
    options: {
        dryRun: { type: 'boolean', description: 'Check the input against the schema without calling the tool' },
        confirm: { type: 'boolean', description: 'Allow a tool that changes or deletes data it cannot restore' },
        projectId: { type: 'string', placeholder: 'id', description: 'Call the tool in this project instead' },
        organizationId: {
            type: 'string',
            placeholder: 'id',
            description: 'The organization for organization-level tools',
        },
    },
    notes: 'The tool decides the scopes. `hog api info <tool>` lists them, and a refusal names the ones the key is missing.',
    examples: [
        'hog api call feature-flag-get-all \'{"limit": 5}\'',
        'echo \'{"key": "beta"}\' | hog api call create-feature-flag - --dry-run',
        'hog api call delete-feature-flag \'{"id": 12}\' --confirm',
    ],

    async run({ args, options, ctx }) {
        const library = await ctx.apiTools()
        const tool = findTool(library, args.tool)
        const validation = library.validate(tool.name, parseInput(args.input))
        if (!validation.valid) {
            throw new HogError(
                'invalid_input',
                validation.error,
                `Run \`hog api schema ${tool.name}\` to see the input it takes.`,
                EXIT_USAGE
            )
        }
        if (options.dryRun) {
            return { tool: tool.name, valid: true, input: validation.input }
        }
        if (tool.destructive && !options.confirm) {
            throw new HogError(
                'needs_confirmation',
                `${tool.name} changes or deletes data it cannot restore.`,
                'Run it again with --confirm.'
            )
        }

        const connection = await apiConnection(ctx, options)
        const result = await library.call(tool.name, validation.input, connection, options.confirm === true)
        await library.flush()
        if (result.ok) {
            return result.value
        }
        // PostHog names one missing scope per refusal, so look up the key to name all of them.
        if (result.error.code === 'permission_denied') {
            const granted = await grantedScopes(ctx, library)
            const missing = granted ? library.missingScopes(granted, tool.requiredScopes) : []
            if (missing.length > 0) {
                throw missingScopesError(tool.name, missing)
            }
        }
        throw toHogError(result.error, tool.name)
    },

    telemetry: ({ args, options }) => ({ tool: args.tool, confirm: options.confirm === true }),
})
