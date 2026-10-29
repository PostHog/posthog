import { defineCommand } from '@/core/command'
import { resolveJsRelease } from '@/error-tracking/js-flow'
import { fetchOrCreateRelease, findRelease, releaseHashId, type Release } from '@/error-tracking/release'
import { releaseFields } from '@/error-tracking/run'
import { SymbolSetClient } from '@/error-tracking/upload'

import { readOptions, RELEASE_OPTIONS } from './shared'

export default defineCommand({
    description: 'Find or create the release this build belongs to',
    writes: true,
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
        build: RELEASE_OPTIONS.build,
        infoPlist: RELEASE_OPTIONS.infoPlist,
        dryRun: {
            type: 'boolean',
            description: 'Look the release up without creating it. The ID is null when PostHog has no such release yet',
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
        'hog et release --info-plist ios/App/Info.plist',
    ],

    async run({ options, ctx }): Promise<(Omit<Release, 'id'> & { id: string | null }) | null> {
        const settings = await readOptions(options, ctx)
        const fields = await releaseFields(ctx, settings)
        const resolved = resolveJsRelease(fields, ctx.runtime.env, ctx.runtime.cwd(), [])
        if (!resolved) {
            return null
        }
        const client = new SymbolSetClient(ctx.runtime, await ctx.credentials())
        if (options.dryRun) {
            const existing = await findRelease(client, resolved.name, resolved.version)
            const { id, hash_id, version, project } = existing ?? {
                id: null,
                hash_id: releaseHashId(resolved.name, resolved.version),
                version: resolved.version,
                project: resolved.name,
            }
            return { id, hash_id, version, project }
        }
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
        if (result?.id) {
            out.line(result.id)
        }
    },
})
