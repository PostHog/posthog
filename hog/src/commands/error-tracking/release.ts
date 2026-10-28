import { defineCommand } from '@/core/command'
import { resolveJsRelease } from '@/error-tracking/js-flow'
import { fetchOrCreateRelease, type Release } from '@/error-tracking/release'
import { releaseFields } from '@/error-tracking/run'
import { SymbolSetClient } from '@/error-tracking/upload'

import { readOptions } from './shared'

export default defineCommand({
    description: 'Find or create the release this build belongs to',
    options: {
        releaseName: {
            type: 'string',
            placeholder: 'name',
            description: 'The release name. Defaults to the git repository name',
        },
        releaseVersion: {
            type: 'string',
            placeholder: 'version',
            description: 'The release version. Defaults to the git commit',
        },
        build: {
            type: 'string',
            placeholder: 'build',
            description: 'A build number, added to the version as version+build',
        },
    },
    scopes: ['error_tracking:write'],
    notes: [
        'Build tools that set the release ID themselves use this to get the same release `hog error-tracking inject` would use.',
        'Without a name and a version from the flags, posthog.json or git, there is no release, and the result is null.',
    ].join('\n'),
    examples: [
        'RELEASE_ID=$(hog error-tracking release -o text)',
        'hog et release --release-name web --release-version 2.1.0',
    ],

    async run({ options, ctx }): Promise<Release | null> {
        const settings = readOptions(options, ctx.runtime.env)
        const fields = await releaseFields(ctx, settings)
        const resolved = resolveJsRelease(fields, ctx.runtime.env, ctx.runtime.cwd(), [])
        if (!resolved) {
            return null
        }
        const client = new SymbolSetClient(ctx.runtime, await ctx.credentials())
        const release = await fetchOrCreateRelease(
            client,
            resolved.name,
            resolved.version,
            resolved.git ? { git: resolved.git } : {}
        )
        return { id: release.id, hash_id: release.hash_id, version: release.version, project: release.project }
    },

    // Just the ID, so `$(hog error-tracking release -o text)` gives what a build script needs.
    human({ result, out }) {
        if (result) {
            out.line(result.id)
        }
    },
})
