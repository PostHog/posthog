import { join, relative } from 'node:path'
import { z } from 'zod'

import type { SkillAssetStatus, SkillsLibrary, SkillsRelease } from '@posthog/mcp/src/cli/library-types'

import { printDownloadWarnings } from '@/commands/learn'
import { KNOWN_AGENTS, knownAgent } from '@/core/agent'
import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import { findGitRoot, isInside, realWritePath } from '@/core/paths'
import type { Env, Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'

import { LIST_HINT, SHARED_SKILL_FOLDER, SKILL_FOLDERS, skillsError } from './shared'

const AgentName = z.enum(KNOWN_AGENTS, { error: (issue) => `Unknown agent "${String(issue.input)}".` })

const AGENT_FAILURE = {
    code: 'unknown_agent',
    hint: `Pass one of: ${KNOWN_AGENTS.join(', ')}.`,
    exitCode: EXIT_USAGE,
}

interface Target {
    agent: string | null
    folder: string
}

interface AddedSkill {
    id: string
    agent: string | null
    path: string
    status: 'installed' | 'already_installed'
}

interface AddResult {
    root: string
    rootKind: 'repository' | 'folder'
    agentSource: 'option' | 'detected' | 'none'
    skills: AddedSkill[]
    assets: SkillAssetStatus[]
}

function skillTargets(
    chosen: readonly string[] | undefined,
    detected: string | undefined,
    env: Env
): { source: AddResult['agentSource']; targets: Target[] } {
    if (chosen?.length) {
        const agents = [...new Set(chosen.map((name) => parseOrThrow(AgentName, name, AGENT_FAILURE)))]
        return { source: 'option', targets: agents.map((agent) => ({ agent, folder: SKILL_FOLDERS[agent] })) }
    }

    if (detected === undefined) {
        return { source: 'none', targets: [{ agent: null, folder: SHARED_SKILL_FOLDER }] }
    }

    const known = knownAgent(detected, env)
    return {
        source: 'detected',
        targets: [{ agent: known ?? detected, folder: known ? SKILL_FOLDERS[known] : SHARED_SKILL_FOLDER }],
    }
}

// The library refuses the same writes. Checking here as well names the folder in hog's own error.
async function assertInsideRoot(runtime: Runtime, root: string, path: string): Promise<void> {
    const realRoot = await runtime.realPath(root)
    if (isInside(realRoot, await realWritePath(runtime, path))) {
        return
    }

    throw new HogError(
        'unsafe_skill_path',
        `${path} points outside ${root} through a symlink, so hog can't install the skill there.`,
        'Remove the symlink, or pass --agent to add the skills to another folder.'
    )
}

async function installOne(
    library: SkillsLibrary,
    release: SkillsRelease,
    runtime: Runtime,
    root: string,
    id: string,
    folder: string,
    force: boolean
): Promise<Pick<AddedSkill, 'path' | 'status'>> {
    const path = join(root, folder, id)
    await assertInsideRoot(runtime, root, path)

    const result = await library.install(id, { cwd: root, force, skillsDir: folder, release })
    if (result.ok) {
        return { path, status: 'installed' }
    }

    if (result.error.code === 'already_installed') {
        return { path, status: 'already_installed' }
    }

    throw skillsError(result.error)
}

export default defineCommand({
    description: 'Add PostHog skills to this repository, in the folder your agent reads',
    args: {
        ids: { description: 'The skill IDs to add, from `hog skills list`', variadic: true },
    },
    options: {
        agent: {
            type: 'string',
            multiple: true,
            placeholder: 'name',
            description: `The agent to add the skills for, instead of the one running hog. Repeat it to add several. One of: ${KNOWN_AGENTS.join(', ')}`,
        },
        force: { type: 'boolean', description: 'Replace a skill that is already installed' },
    },
    writes: true,
    notes: [
        'Skills go in the closest git repository, or in the current folder outside one. Claude Code reads `.claude/skills`. Most other agents read `.agents/skills`.',
        'Without `--agent`, skills go in the folder of the agent running hog, or in `.agents/skills` if no agent is running it. Skills are public, so `hog skills add` needs no login.',
    ].join('\n'),
    examples: [
        'hog skills add audit-feature-flags error-tracking-nextjs',
        'hog skills add audit-feature-flags --agent claude-code --agent codex',
    ],

    async run({ args, options, ctx }): Promise<AddResult> {
        const { source, targets } = skillTargets(options.agent, ctx.mode.agent, ctx.runtime.env)

        const repository = await findGitRoot(ctx.runtime)
        const root = repository?.root ?? ctx.runtime.cwd()

        // Every id is checked before the first write, so a typo doesn't leave half the skills installed.
        const library = await ctx.skills()
        const listed = await library.installable()
        if (!listed.ok) {
            throw skillsError(listed.error)
        }

        const ids = [...new Set(args.ids)]
        const unknown = ids.filter((id) => !listed.value.skills.some((skill) => skill.id === id))
        if (unknown.length > 0) {
            const names = unknown.map((id) => `"${id}"`).join(', ')
            throw new HogError(
                'unknown_skill',
                `Unknown ${unknown.length === 1 ? 'skill' : 'skills'} ${names}.`,
                LIST_HINT
            )
        }

        // Agents that share a folder share one copy, so each folder installs a skill once.
        const outcomes = new Map<string, Pick<AddedSkill, 'path' | 'status'>>()
        const skills: AddedSkill[] = []
        for (const id of ids) {
            for (const target of targets) {
                const key = join(target.folder, id)
                let outcome = outcomes.get(key)
                if (!outcome) {
                    outcome = await installOne(
                        library,
                        listed.value.release,
                        ctx.runtime,
                        root,
                        id,
                        target.folder,
                        options.force === true
                    )
                    outcomes.set(key, outcome)
                }

                skills.push({ id, agent: target.agent, ...outcome })
            }
        }

        return {
            root,
            rootKind: repository ? 'repository' : 'folder',
            agentSource: source,
            skills,
            assets: listed.value.assets,
        }
    },

    human({ result, out }) {
        printDownloadWarnings(out, result.assets)

        const root = escapeControls(result.root)
        out.line(
            result.rootKind === 'repository'
                ? `Skills go in the git repository at ${root}.`
                : `${root} isn't in a git repository, so the skills go in this folder.`
        )

        if (result.agentSource === 'none') {
            out.line(`No agent is running hog, so the skills go in ${SHARED_SKILL_FOLDER}, which most agents read.`)
            out.line('Pass `--agent` to pick one, such as `--agent claude-code`.')
        }

        for (const skill of result.skills) {
            const path = escapeControls(relative(result.root, skill.path))
            const id = escapeControls(skill.id)
            out.line(
                skill.status === 'installed'
                    ? `Installed ${id} in ${path}`
                    : `${id} is already in ${path}. Pass --force to replace it.`
            )
        }
    },

    agent({ result, out }) {
        out.json(result)
    },

    // Ids only reach here once the published catalog lists them, so they never carry text the caller made up.
    telemetry({ result }) {
        return {
            skills_added: [...new Set(result.skills.map((skill) => skill.id))].sort(),
            agent_source: result.agentSource,
            already_installed: result.skills.filter((skill) => skill.status === 'already_installed').length,
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
