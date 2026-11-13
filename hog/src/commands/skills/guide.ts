import { defineCommand } from '@/core/command'

interface SkillsGuide {
    commands: { command: string; description: string }[]
}

const COMMANDS: SkillsGuide['commands'] = [
    { command: 'hog skills list', description: 'See every skill, for using PostHog and for adding it to your code' },
    { command: 'hog skills search <keywords...>', description: 'Find skills by keywords' },
    { command: 'hog skills read <skill>', description: 'Read a skill without adding it' },
    {
        command: 'hog skills add <skill...>',
        description: 'Add skills to this repository, in the folder your agent reads',
    },
]

export default defineCommand({
    description: 'Show how to find, read and add PostHog skills',
    examples: ['hog skills'],

    async run(): Promise<SkillsGuide> {
        return { commands: COMMANDS }
    },

    human({ result, out }) {
        const width = Math.max(...result.commands.map(({ command }) => command.length))

        out.line('PostHog skills are guides an agent follows for PostHog tasks.')
        out.line()
        for (const { command, description } of result.commands) {
            out.line(`  ${out.style(command.padEnd(width), 'bold')}  ${description}`)
        }
    },

    agent({ result, out }) {
        out.json(result)
    },
})
