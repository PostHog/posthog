import type { SkillAssetStatus, SkillsError } from '@posthog/mcp/src/cli/library-types'

import type { KnownAgent } from '@/core/agent'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'

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

export const LIST_HINT = 'Run `hog skills list` to see every skill you can add.'

const SKILL_NAMESPACE = 'posthog:'

// `hog skills list` names skills without a prefix. Older skill text also names them as `posthog:<name>`.
export function skillName(input: string): string {
    return input.startsWith(SKILL_NAMESPACE) ? input.slice(SKILL_NAMESPACE.length) : input
}

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

const ASSET_NAMES: Record<SkillAssetStatus['name'], string> = {
    'product-skills': 'the PostHog product skills',
    'context-mill': 'the setup skills, such as posthog:instrument-integration',
}

export function offlineError(error: SkillsError): HogError {
    const assets = error.assets ?? []
    const failures = assets.map((asset) => `\n  ${asset.url}: ${asset.failure}`).join('')

    return new HogError(
        'skills_offline',
        `${error.message}${failures}`,
        'Check your internet connection, then run the command again.',
        undefined,
        { assets }
    )
}

// Why the skills may be out of date, shown after the command's result.
export function downloadWarnings(assets: readonly SkillAssetStatus[]): string[] {
    const warnings: string[] = []
    for (const asset of assets) {
        const outcome =
            asset.origin === 'cache' && asset.fetchedAt
                ? `. Using the copy saved on ${asset.fetchedAt.slice(0, 16).replace('T', ' ')} UTC`
                : asset.origin === 'unavailable'
                  ? ", and there's no saved copy"
                  : undefined

        if (outcome) {
            const failure = escapeControls(asset.failure ?? '')
            warnings.push(`hog couldn't download ${ASSET_NAMES[asset.name]} (${failure})${outcome}.`)
        }
    }
    return warnings
}
