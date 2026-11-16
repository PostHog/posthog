import { join, relative } from 'node:path'
import { z } from 'zod'

import type { SkillAssetStatus, SkillsLibrary, SkillsRelease } from '@posthog/mcp/src/cli/library-types'

import { KNOWN_AGENTS, knownAgent } from '@/core/agent'
import { defineCommand } from '@/core/command'
import { EXIT_USAGE, HogError } from '@/core/errors'
import { escapeControls, type Output } from '@/core/output'
import { findGitRoot, isInside, realWritePath } from '@/core/paths'
import type { Env, Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'

import {
    downloadWarnings,
    LIST_HINT,
    offlineError,
    SHARED_SKILL_FOLDER,
    SKILL_FOLDERS,
    skillName,
    skillsError,
} from './shared'

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
    // As `hog skills list` names it, such as `tracing-nodejs`.
    name: string
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
    name: string,
    folder: string,
    force: boolean
): Promise<Pick<AddedSkill, 'path' | 'status'>> {
    const path = join(root, folder, name)
    await assertInsideRoot(runtime, root, path)

    const result = await library.install(name, { cwd: root, force, skillsDir: folder, release })
    if (result.ok) {
        return { path, status: 'installed' }
    }

    if (result.error.code === 'already_installed') {
        return { path, status: 'already_installed' }
    }

    throw skillsError(result.error)
}

function addReport(result: AddResult, out: Output): Parameters<Output['report']>[0] {
    const root = escapeControls(result.root)
    const added = [...new Set(result.skills.filter((skill) => skill.status === 'installed').map((skill) => skill.name))]
    const kept = [
        ...new Set(result.skills.filter((skill) => skill.status === 'already_installed').map((skill) => skill.name)),
    ]
    const list = (names: readonly string[]): string => names.map(escapeControls).join(', ')

    // One line per folder written, so agents that share a folder show once.
    const folders = new Map(result.skills.map((skill) => [skill.path, skill]))
    const effects = [...folders.values()].map((skill) => {
        const path = escapeControls(relative(result.root, skill.path))
        return skill.status === 'installed'
            ? `Wrote ${path}`
            : `Left ${path} as it was, because the skill is already there`
    })

    const notes: string[] = []
    if (result.rootKind === 'folder') {
        notes.push(`${root} isn't in a git repository, so the skills went in this folder.`)
    }
    if (result.agentSource === 'none') {
        notes.push(
            `No agent is running hog, so the skills went in ${SHARED_SKILL_FOLDER}, which most agents read. To add them for one agent, pass ${out.style('--agent', 'bold')}, as in ${out.style('--agent claude-code', 'bold')}.`
        )
    }
    if (kept.length > 0) {
        notes.push(
            `To replace a skill that is already there, run the command again with ${out.style('--force', 'bold')}.`
        )
    }

    return {
        result:
            added.length > 0
                ? `Added ${list(added)} to ${root}`
                : `Nothing to add: ${list(kept)} ${kept.length === 1 ? 'is' : 'are'} already in ${root}`,
        status: added.length > 0 ? 'done' : 'unchanged',
        effects,
        warnings: downloadWarnings(result.assets),
        notes,
    }
}

export default defineCommand({
    description: 'Add PostHog skills to this repository, in the folder your agent reads',
    args: {
        skills: {
            description: 'The skills to add, as `hog skills list` names them, such as tracing-nodejs',
            variadic: true,
        },
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
        'Any skill `hog skills list` names can be added, with or without the `posthog:` prefix. Skills go in the closest git repository, or in the current folder outside one. Claude Code reads `.claude/skills`. Most other agents read `.agents/skills`.',
        'Without `--agent`, skills go in the folder of the agent running hog, or in `.agents/skills` if no agent is running it. Skills are public, so `hog skills add` needs no login.',
    ].join('\n'),
    examples: [
        'hog skills add tracing-nodejs analyzing-funnel-correlation',
        'hog skills add audit-feature-flags --agent claude-code --agent codex',
    ],

    async run({ args, options, ctx }): Promise<AddResult> {
        const { source, targets } = skillTargets(options.agent, ctx.mode.agent, ctx.runtime.env)

        const repository = await findGitRoot(ctx.runtime)
        const root = repository?.root ?? ctx.runtime.cwd()

        // Every name is checked before the first write, so a typo doesn't leave half the skills installed.
        const library = await ctx.skills()
        const listed = await library.catalog()
        if (!listed.ok) {
            throw skillsError(listed.error)
        }

        const names = [...new Set(args.skills.map(skillName))]
        const unknown = names.filter((name) => !listed.value.skills.some((skill) => skill.name === name))
        if (unknown.length > 0) {
            const quoted = unknown.map((name) => `"${name}"`).join(', ')
            // A download that failed with no saved copy leaves its skills out of the list, so a name missing
            // from it may still be a real skill.
            const missing = listed.value.assets.filter((asset) => asset.origin === 'unavailable')
            if (missing.length > 0) {
                throw offlineError({
                    code: 'offline',
                    message: `Couldn't download all the PostHog skills, so hog can't check ${quoted}.`,
                    assets: missing,
                })
            }
            throw new HogError(
                'unknown_skill',
                `Unknown ${unknown.length === 1 ? 'skill' : 'skills'} ${quoted}.`,
                LIST_HINT
            )
        }

        // Agents that share a folder share one copy, so each folder installs a skill once.
        const outcomes = new Map<string, Pick<AddedSkill, 'path' | 'status'>>()
        const skills: AddedSkill[] = []
        for (const name of names) {
            for (const target of targets) {
                const key = join(target.folder, name)
                let outcome = outcomes.get(key)
                if (!outcome) {
                    outcome = await installOne(
                        library,
                        listed.value.release,
                        ctx.runtime,
                        root,
                        name,
                        target.folder,
                        options.force === true
                    )
                    outcomes.set(key, outcome)
                }

                skills.push({ name, agent: target.agent, ...outcome })
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
        out.report(addReport(result, out))
    },

    agent({ result, out }) {
        out.json(result)
    },

    // Ids only reach here once the published catalog lists them, so they never carry text the caller made up.
    telemetry({ result }) {
        return {
            skills_added: [...new Set(result.skills.map((skill) => skill.name))].sort(),
            agent_source: result.agentSource,
            already_installed: result.skills.filter((skill) => skill.status === 'already_installed').length,
            skill_asset_origins: Object.fromEntries(result.assets.map((asset) => [asset.name, asset.origin])),
        }
    },
})
