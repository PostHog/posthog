import { createHash } from 'node:crypto'
import { z } from 'zod'

import { defineCommand } from '@/core/command'
import { HogError } from '@/core/errors'
import { escapeControls } from '@/core/output'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow, type ParseFailure } from '@/core/schema'
import { extractFile } from '@/updates/archive'
import { rememberRelease } from '@/updates/check'
import { detectInstallMethod, type InstallKind, type InstallMethod, upgradeCommand } from '@/updates/install-method'
import { type Artifact, fetchManifest, type Manifest } from '@/updates/manifest'
import { binaryName, targetFor } from '@/updates/targets'
import { isNewer, parseVersion } from '@/updates/version'

const VersionOption = z
    .string()
    .trim()
    .transform((text) => text.replace(/^v/, ''))
    .refine((text) => parseVersion(text) !== undefined, { error: 'Pass a version like 0.1.0-alpha.4.' })

type Action = 'upgraded' | 'ran' | 'declined' | 'run_command' | 'explain' | 'up_to_date' | 'available'

interface UpgradeResult {
    action: Action
    current: string
    latest: string
    updateAvailable: boolean
    method: InstallKind
    path: string
    project: string | null
    command: string | null
}

const PACKAGE_MANAGERS: readonly InstallKind[] = ['homebrew', 'npm-global', 'pnpm-global', 'bun-global']
const SELF_UPDATING: readonly InstallKind[] = ['script', 'standalone']

const MANAGER_NAMES: Partial<Record<InstallKind, string>> = {
    homebrew: 'Homebrew',
    'npm-global': 'npm',
    'pnpm-global': 'pnpm',
    'bun-global': 'bun',
}

async function download(runtime: Runtime, urls: string[]): Promise<Uint8Array> {
    for (const url of urls) {
        try {
            const response = await runtime.fetch(url, { timeoutMs: 300_000, skipRateLimit: true })
            if (response.ok) {
                return new Uint8Array(await response.arrayBuffer())
            }
        } catch {}
    }
    throw new HogError(
        'download_failed',
        `hog couldn't download ${urls[0]}.`,
        'Check your connection and run `hog upgrade` again.'
    )
}

function sha256(bytes: Uint8Array): string {
    return createHash('sha256').update(bytes).digest('hex')
}

async function replaceSelf(runtime: Runtime, method: InstallMethod, manifest: Manifest): Promise<void> {
    const target = targetFor(runtime.platform, runtime.arch, await runtime.isMusl())
    const artifact: Artifact | undefined = target && manifest.artifacts[target.id]
    if (!target || !artifact) {
        throw new HogError(
            'no_build_for_platform',
            `hog ${manifest.version} has no build for ${runtime.platform} on ${runtime.arch}.`,
            'See https://github.com/PostHog/posthog/tree/master/hog for the supported platforms.'
        )
    }

    const archive = await download(runtime, [
        `${manifest.baseUrl}${artifact.file}`,
        `${manifest.mirrorUrl}${artifact.file}`,
    ])
    if (sha256(archive) !== artifact.sha256) {
        throw new HogError(
            'checksum_mismatch',
            `${artifact.file} doesn't match the checksum in the release manifest, so hog left your install as it was.`,
            'Run `hog upgrade` again. If it fails again, reinstall with the install script.'
        )
    }

    const binary = extractFile(archive, artifact.file, binaryName(target))
    try {
        await runtime.replaceExecutable(method.path, binary)
    } catch (error) {
        const code = (error as NodeJS.ErrnoException).code
        if (code === 'EACCES' || code === 'EPERM') {
            throw new HogError(
                'upgrade_not_permitted',
                `hog can't replace ${method.path}: you don't have permission to write there.`,
                'Run `hog upgrade` as the user who installed hog, or reinstall hog in a folder you own with the install script.'
            )
        }
        throw error
    }
}

export default defineCommand({
    description: 'Update hog to the latest version',
    options: {
        check: { type: 'boolean', description: 'Only report whether a newer version exists, and change nothing' },
        version: {
            type: 'string',
            placeholder: 'version',
            parse: (raw: string, failure: ParseFailure) => parseOrThrow(VersionOption, raw, failure),
            description: 'Install this version instead of the latest one',
        },
    },
    writes: true,
    notes: [
        'hog never updates itself on its own. It replaces its own binary only when the install script put it there or you downloaded it yourself.',
        'A copy that Homebrew, npm, pnpm or bun installed updates through that package manager: at a terminal hog asks, then runs its command. Agents get the command to run.',
    ].join('\n'),
    examples: ['hog upgrade', 'hog upgrade --check', 'hog upgrade --version 0.1.0-alpha.4'],

    async run({ options, ctx }): Promise<UpgradeResult> {
        const { runtime } = ctx
        const method = await detectInstallMethod(runtime)
        const manifest = await fetchManifest(runtime, { version: options.version })
        if (options.version === undefined) {
            await rememberRelease(runtime, manifest)
        }

        const current = runtime.build.version
        const updateAvailable =
            options.version === undefined ? isNewer(manifest.version, current) : manifest.version !== current
        const command = upgradeCommand(method, options.version)
        const result = (action: Action, ran?: string | null): UpgradeResult => ({
            action,
            current,
            latest: manifest.version,
            updateAvailable,
            method: method.kind,
            path: method.path,
            project: method.project ?? null,
            command: ran === undefined ? (command ?? null) : ran,
        })

        if (!updateAvailable) {
            return result('up_to_date', null)
        }
        if (options.check) {
            return result('available')
        }

        if (SELF_UPDATING.includes(method.kind)) {
            await replaceSelf(runtime, method, manifest)
            return result('upgraded', null)
        }

        if (PACKAGE_MANAGERS.includes(method.kind) && command) {
            const prompts = ctx.prompts
            if (!prompts) {
                return result('run_command')
            }
            if (!(await prompts.confirm(`Run ${command}?`))) {
                return result('declined')
            }
            const exitCode = await runtime.runCommand(command.split(' '))
            if (exitCode !== 0) {
                throw new HogError(
                    'upgrade_command_failed',
                    `\`${command}\` exited with code ${exitCode}.`,
                    'Read its output above, fix the problem, and run the command yourself.'
                )
            }
            return result('ran')
        }

        return result('explain')
    },

    human({ result, out }) {
        const command = result.command ? out.style(result.command, 'bold') : ''
        const path = escapeControls(result.path)
        const available = `hog ${result.latest} is available. You have ${result.current}.`
        switch (result.action) {
            case 'up_to_date':
                out.report({ status: 'unchanged', result: `hog ${result.current} is the latest version` })
                return
            case 'upgraded':
                out.report({
                    result: `Updated hog from ${result.current} to ${result.latest}`,
                    effects: [`Replaced ${path}`],
                })
                return
            case 'ran':
                out.report({ result: `Updated hog to ${result.latest}`, effects: [`Ran ${command}`] })
                return
            case 'available':
                out.report({ status: 'unchanged', result: available, notes: [`Run ${command} to update.`] })
                return
            case 'declined':
            case 'run_command':
                out.report({
                    status: 'unchanged',
                    result: available,
                    notes: [
                        `${MANAGER_NAMES[result.method] ?? 'A package manager'} manages this copy. Update it with ${command}`,
                    ],
                })
                return
            case 'explain':
                out.report({
                    status: 'unchanged',
                    result: available,
                    notes: [
                        result.method === 'npx'
                            ? `This copy is in a package runner's cache at ${path}. Run ${command} to use the latest version.`
                            : result.method === 'project'
                              ? `This copy is a dependency of ${escapeControls(result.project ?? '')}. Update @posthog/hog in its package.json.`
                              : 'This copy runs from source. Pull the latest changes instead.',
                    ],
                })
        }
    },

    agent({ result, out }) {
        out.json(result)
    },

    telemetry: ({ result }) => ({ upgrade_action: result.action, upgrade_method: result.method }),
})
