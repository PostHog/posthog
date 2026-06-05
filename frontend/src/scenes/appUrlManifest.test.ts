import { readFileSync, writeFileSync } from 'fs'
import path from 'path'

import { addProjectIdIfMissing } from 'lib/utils/router-utils'
import { urls } from 'scenes/urls'

import { buildAppUrlManifest } from './appUrlManifest'

// The MCP `generate-app-url` tool consumes this committed artifact. Source of truth is `urls`; this
// test regenerates it (run `pnpm --filter=@posthog/frontend build:app-urls`) and fails on drift.
const MANIFEST_PATH = path.resolve(__dirname, '../../../services/mcp/src/tools/links/app-url-manifest.json')

// Reuse the app's own routing oracle (pathsWithoutProjectId) instead of duplicating the list. A fixed
// team id makes it deterministic regardless of logged-in state.
const isProjectScoped = (template: string): boolean => addProjectIdIfMissing(template, 999).includes('/project/999')

describe('app-url manifest', () => {
    const { manifest, excluded, baseOnly } = buildAppUrlManifest(urls as Record<string, unknown>, isProjectScoped)

    it('derives correct templates for representative entity links', () => {
        // The regression that motivated this: a person UUID lives at /persons/, a distinct id at /person/.
        expect(manifest.personByUUID).toEqual({ template: '/persons/{uuid}', params: ['uuid'], scope: 'project' })
        expect(manifest.personByDistinctId).toEqual({ template: '/person/{id}', params: ['id'], scope: 'project' })
        expect(manifest.replaySingle).toEqual({ template: '/replay/{id}', params: ['id'], scope: 'project' })
        expect(manifest.event).toEqual({
            template: '/events/{id}/{timestamp}',
            params: ['id', 'timestamp'],
            scope: 'project',
        })
        expect(manifest.sessionProfile).toEqual({ template: '/sessions/{id}', params: ['id'], scope: 'project' })
        expect(manifest.dashboard).toEqual({ template: '/dashboard/{id}', params: ['id'], scope: 'project' })
    })

    it('captures builders defined directly in urls.ts, not just product manifests', () => {
        // These are not in any product manifest — they would be missing if we harvested manifests alone.
        expect(manifest.event).toBeTruthy()
        expect(manifest.sessionProfile).toBeTruthy()
        expect(manifest.annotation).toBeTruthy()
    })

    it('marks org/account pages as global (no project prefix)', () => {
        expect(manifest.instanceStatus?.scope).toBe('global')
        expect(manifest.organizationBillingSection?.scope).toBe('global')
    })

    it('committed MCP manifest is up to date (run `pnpm --filter=@posthog/frontend build:app-urls` to regenerate)', () => {
        if (process.env.UPDATE_APP_URL_MANIFEST) {
            writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 4) + '\n')
            // eslint-disable-next-line no-console
            console.info(
                `[app-urls] wrote ${Object.keys(manifest).length} entries; ${baseOnly.length} base-only:`,
                baseOnly
            )
            // eslint-disable-next-line no-console
            console.info('[app-urls] excluded:', excluded)
        }
        const committed = JSON.parse(readFileSync(MANIFEST_PATH, 'utf-8'))
        expect(committed).toEqual(manifest)
    })
})
