import { defineCommand, type CommandTree } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { rootText, TOPICS } from '@/instructions/topics'
import { VERSION } from '@/version'

type InstructionsResult =
    | { kind: 'page'; topic: string | null; version: string; text: string }
    | { kind: 'list'; topics: { name: string; description: string }[] }

function commandPaths(tree: CommandTree, prefix = ''): string[] {
    return Object.entries(tree).flatMap(([name, node]) => {
        const path = prefix ? `${prefix} ${name}` : name
        switch (node.kind) {
            case 'group':
                return [path, ...commandPaths(node.commands, path)]
            case 'command':
                return [path]
            case 'legacy':
                return []
        }
    })
}

// Matches the full path first, so `schema` finds `hog schema` before `hog api schema`.
function findCommand(tree: CommandTree, name: string): string | undefined {
    const paths = commandPaths(tree)
    return paths.find((path) => path === name) ?? paths.find((path) => path.split(' ').at(-1) === name)
}

function unknownTopic(tree: CommandTree, topic: string): HogError {
    const topics = `The topics are ${TOPICS.map((entry) => entry.name).join(', ')}.`
    const command = findCommand(tree, topic)
    if (command) {
        return new HogError(
            'unknown_topic',
            `\`${topic}\` is a command, not an instructions topic.`,
            `Run \`hog ${command} --help\` to see how to use it. ${topics}`,
            EXIT_USAGE
        )
    }
    return new HogError(
        'unknown_topic',
        `There is no instructions topic named "${topic}".`,
        `${topics} Run \`hog instructions\` for the overview.`,
        EXIT_USAGE
    )
}

export default defineCommand({
    description: 'Show how coding agents use hog. Agents run this first',
    args: { topic: { description: 'A topic, from `hog instructions --list`', optional: true } },
    options: { list: { type: 'boolean', description: 'List the topics' } },
    notes: 'The instructions come with hog, so they match the installed version.',
    examples: ['hog instructions', 'hog instructions --list', 'hog instructions auth'],

    run({ args, options, ctx }): InstructionsResult {
        if (options.list) {
            return { kind: 'list', topics: TOPICS.map(({ name, description }) => ({ name, description })) }
        }

        if (args.topic === undefined) {
            return { kind: 'page', topic: null, version: VERSION, text: rootText() }
        }

        const topic = TOPICS.find((entry) => entry.name === args.topic)
        if (!topic) {
            throw unknownTopic(ctx.tree, args.topic)
        }
        return { kind: 'page', topic: topic.name, version: VERSION, text: topic.text }
    },

    human({ result, out }) {
        if (result.kind === 'page') {
            out.line(result.text.trimEnd())
            return
        }

        const width = Math.max(...result.topics.map(({ name }) => name.length))
        for (const { name, description } of result.topics) {
            out.line(`  ${out.style(name.padEnd(width), 'bold')}  ${description}`)
        }
        out.notes({ notes: [`Run ${out.style('hog instructions <topic>', 'bold')} to read one.`] })
    },

    agent({ result, out }) {
        out.json(result)
    },

    telemetry: ({ result }) => ({
        topic: result.kind === 'page' ? (result.topic ?? 'overview') : null,
        list: result.kind === 'list',
    }),
})
