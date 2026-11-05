import { defineCommand } from '@/core/command'
import { findTool, grantedScopes, groupSlug, toolKind } from '@/posthog/api-tools'

interface InputSchema {
    properties?: Record<string, { type?: string; description?: string }>
    required?: string[]
}

export default defineCommand({
    description: 'Show what an API tool does, the scopes it needs, and the input it takes',
    args: {
        tool: { description: 'The tool name, as `hog api tools` lists it' },
    },
    examples: ['hog api info feature-flag-get-all'],

    async run({ args, ctx }) {
        const library = await ctx.apiTools()
        const tool = findTool(library, args.tool)
        const [granted, schema] = await Promise.all([grantedScopes(ctx, library), library.schema(tool.name)])
        return {
            name: tool.name,
            title: tool.title,
            description: tool.description,
            group: groupSlug(tool.group),
            kind: toolKind(tool),
            idempotent: tool.idempotent,
            requiresAiConsent: tool.requiresAiConsent,
            requiredScopes: tool.requiredScopes,
            missingScopes: granted ? library.missingScopes(granted, tool.requiredScopes) : null,
            input: schema,
        }
    },

    human({ result, out }) {
        out.line(out.style(`${result.name}: ${result.title}`, 'bold'))
        out.line(result.description)
        out.line()
        out.line(`Group: ${result.group}`)
        out.line(`Kind: ${result.kind}${result.kind === 'destructive' ? ', needs --confirm' : ''}`)
        out.line(`Scopes: ${result.requiredScopes.join(', ') || 'none'}`)
        if (result.requiresAiConsent) {
            out.line('Sends data to an AI provider, so the organization must allow AI data processing.')
        }
        if (result.missingScopes?.length) {
            out.line(out.style(`Missing scopes: ${result.missingScopes.join(', ')}`, 'red'))
        }
        const schema = result.input as InputSchema
        const fields = Object.entries(schema.properties ?? {})
        if (fields.length > 0) {
            out.line()
            out.table(
                ['field', 'type', 'required', 'description'],
                fields.map(([name, field]) => [
                    name,
                    field.type ?? null,
                    schema.required?.includes(name) ?? false,
                    field.description ?? null,
                ])
            )
        }
        out.line(out.style(`Run \`hog api schema ${result.name} <field>\` to see a nested field.`, 'dim'))
    },

    telemetry: ({ args }) => ({ tool: args.tool }),
})
