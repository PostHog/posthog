import type { SkillCommands } from '@posthog/mcp/src/cli/library-types'

// The skills commands hog prints. The skills library also names them in the text it serves, in place
// of the MCP `learn` command.
export const SKILL_COMMANDS: SkillCommands = {
    read: (skill, file, lines) =>
        [
            'hog skills read',
            skill,
            ...(file === undefined ? [] : ['--file', file]),
            ...(lines === undefined ? [] : ['--lines', lines]),
        ].join(' '),
    search: (keywords) => `hog skills search ${keywords}`,
    list: 'hog skills list',
}
