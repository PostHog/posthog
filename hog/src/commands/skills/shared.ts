import type { SkillsError } from '@posthog/mcp/src/cli/library-types'

import { offlineError } from '@/commands/learn'
import type { KnownAgent } from '@/core/agent'
import { EXIT_USAGE, HogError } from '@/core/errors'

// The project folder each agent reads skills from, from the agent table of the `skills` package on npm,
// which `npx skills add` runs. Agents that share `.agents/skills` read the same copy.
export const SKILL_FOLDERS: Readonly<Record<KnownAgent, string>> = {
    'claude-code': '.claude/skills',
    codex: '.agents/skills',
    cursor: '.agents/skills',
    'gemini-cli': '.agents/skills',
    cline: '.agents/skills',
    opencode: '.agents/skills',
    augment: '.augment/skills',
    antigravity: '.agents/skills',
    'github-copilot': '.agents/skills',
}

export const SHARED_SKILL_FOLDER = '.agents/skills'

export const LIST_HINT = 'Run `hog skills list` to see the skills you can add.'

export function skillsError(error: SkillsError): HogError {
    switch (error.code) {
        case 'offline':
            return offlineError(error)
        case 'install_failed':
            return new HogError(
                'skill_install_failed',
                error.message,
                'Check that you can write to the skills folder, then run the command again.'
            )
        case 'usage':
            return new HogError('invalid_skill_id', error.message, LIST_HINT, EXIT_USAGE)
        default:
            return new HogError(error.code, error.message, LIST_HINT)
    }
}
