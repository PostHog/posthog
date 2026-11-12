import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { parseJson } from '@/core/json'
import {
    findTool,
    grantedScopes,
    missingScopesError,
    toHogError,
    withApiConnection,
    withStaleToolsHint,
} from '@/posthog/api-tools'
import { parseOrganizationId, parseProjectId } from '@/posthog/ids'

const ToolInput = z.record(z.string(), z.unknown(), { error: 'The input must be a JSON object.' })

function parseInput(text: string | undefined): Record<string, unknown> {
    if (text === undefined) {
        return {}
    }
    return parseJson(text, ToolInput, {
        code: 'invalid_json',
        hint: 'Pass one JSON object, like \'{"limit": 10}\'.',
        exitCode: EXIT_USAGE,
    })
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
        projectId: {
            type: 'string',
            placeholder: 'id',
            parse: parseProjectId,
            description: 'Call the tool in this project instead',
        },
        organizationId: {
            type: 'string',
            placeholder: 'id',
            parse: parseOrganizationId,
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

        await ctx.ensureScopes(tool.requiredScopes, `to call ${tool.name}`)
        const result = await withApiConnection(ctx, options, tool.readOnly || tool.idempotent, (connection) =>
            library.call(tool.name, validation.input, connection, options.confirm === true)
        )
        await library.flush()
        if (result.ok) {
            return result.value
        }
        if (result.error.code !== 'permission_denied') {
            throw withStaleToolsHint(result.error, toHogError(result.error, tool.name))
        }
        const credentials = await ctx.credentials()
        // PostHog names one missing scope per refusal, so look up the key to name all of them.
        const granted = await grantedScopes(ctx, library)
        const missing = granted ? library.missingScopes(granted, tool.requiredScopes) : []
        throw missing.length > 0
            ? missingScopesError(tool.name, missing, credentials)
            : toHogError(result.error, tool.name, credentials)
    },

    telemetry: ({ args, options }) => ({ tool: args.tool, confirm: options.confirm === true }),
})
