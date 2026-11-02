import { defineCommand } from '@/core/command'
import { describeAliases, describeCommands, describeGlobalOptions } from '@/core/manifest'
import { VERSION } from '@/version'

export default defineCommand({
    description: 'List every command, for agents and scripts',
    notes: 'Agents can learn the whole CLI from one call: every command, its arguments, options and scopes.',
    examples: ['hog commands -o json'],

    run: ({ ctx }) => ({
        cli: 'hog',
        version: VERSION,
        agent: ctx.mode.agent ?? null,
        agentReason: ctx.mode.agentReason,
        globalOptions: describeGlobalOptions(),
        commands: describeCommands(ctx.tree),
        aliases: describeAliases(ctx.tree),
    }),

    human({ result, out }) {
        const width = Math.max(...result.commands.map((entry) => entry.name.length)) + 2
        for (const entry of result.commands) {
            const use = entry.use ? out.style(`  (use ${entry.use})`, 'dim') : ''
            out.line(`  ${entry.name.padEnd(width)}${entry.description}${use}`)
        }
    },
})
