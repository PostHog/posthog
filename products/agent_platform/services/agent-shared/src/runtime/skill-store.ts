/**
 * Resolves an agent's `source: 'store'` skills LIVE from the PostHog skill store
 * (`llm_analytics_llmskill`) at load time — bundled skills come from the bundle.
 *
 * Reads the MAIN PostHog DB directly (the pool `PgTeamApiKeyResolver` uses).
 * Authz is structural: the freeze-time attach gate already checked the author
 * could read the skill, and every query is scoped to the running revision's own
 * `team_id` — no per-request user credential.
 *
 * No cache for v1 — a store edit must reach running agents on the next load. When
 * hot, project into a team-scoped HyperCache behind this same interface.
 */

import type { Pool } from 'pg'

import { createLogger } from './logger'

export interface SkillStore {
    /**
     * Resolve a store skill's content for the given team.
     *
     * - `version` omitted → the latest published version (tracks edits).
     * - `version` set → that exact (immutable) version.
     * - `file` omitted → the rendered SKILL.md (frontmatter + body).
     * - `file` set → a companion file's raw content from the skill folder.
     *
     * Returns `null` when the skill (or the requested version/file) does not
     * exist. Throws only on an operational DB failure, so the caller can treat
     * that as retryable rather than as a permanent "not found".
     */
    resolve(teamId: number, name: string, version?: number, file?: string): Promise<string | null>
}

interface SkillRow {
    id: string
    name: string
    description: string
    body: string
    license: string | null
    compatibility: string | null
    // JSONB columns — node-postgres returns them already parsed.
    allowed_tools: unknown
    metadata: unknown
    version: number
}

// Latest published version for a (team, name). `is_latest` is the store's own
// "current" marker (one row per name per team); the ORDER BY is a tiebreak.
const LATEST_SQL = `
    SELECT id, name, description, body, license, compatibility, allowed_tools, metadata, version
    FROM llm_analytics_llmskill
    WHERE team_id = $1 AND name = $2 AND deleted = false AND is_latest = true
    ORDER BY version DESC, created_at DESC, id DESC
    LIMIT 1`

// A specific pinned version. Versions are immutable, so no `is_latest` filter.
const BY_VERSION_SQL = `
    SELECT id, name, description, body, license, compatibility, allowed_tools, metadata, version
    FROM llm_analytics_llmskill
    WHERE team_id = $1 AND name = $2 AND version = $3 AND deleted = false
    ORDER BY created_at ASC, id ASC
    LIMIT 1`

const FILE_SQL = `
    SELECT content
    FROM llm_analytics_llmskillfile
    WHERE skill_id = $1 AND path = $2
    LIMIT 1`

/** A YAML-safe double-quoted scalar. JSON string syntax is a subset of YAML's
 *  double-quoted flow scalar, so this escapes quotes/newlines/etc. correctly. */
function yamlScalar(value: string): string {
    return JSON.stringify(value)
}

/**
 * Render a store skill row to a SKILL.md string, mirroring the field set of
 * Django's `render_skill_md` (frontmatter then a blank line then the body).
 * The platform `version` is always present in `metadata`.
 */
function renderSkillMd(row: SkillRow): string {
    const fm: string[] = ['---']
    fm.push(`name: ${yamlScalar(row.name)}`)
    fm.push(`description: ${yamlScalar(row.description)}`)
    if (row.license) {
        fm.push(`license: ${yamlScalar(row.license)}`)
    }
    if (row.compatibility) {
        fm.push(`compatibility: ${yamlScalar(row.compatibility)}`)
    }
    fm.push('metadata:')
    const metadata = row.metadata && typeof row.metadata === 'object' ? (row.metadata as Record<string, unknown>) : {}
    for (const [key, value] of Object.entries(metadata)) {
        // `version` is platform-owned and appended below, so a stored `version`
        // key never duplicates it.
        if (key === 'version') {
            continue
        }
        fm.push(`  ${key}: ${yamlScalar(String(value))}`)
    }
    fm.push(`  version: ${yamlScalar(String(row.version))}`)
    const allowedTools = Array.isArray(row.allowed_tools) ? (row.allowed_tools as unknown[]).map(String) : []
    if (allowedTools.length > 0) {
        fm.push(`allowed-tools: ${allowedTools.join(' ')}`)
    }
    fm.push('---')
    return `${fm.join('\n')}\n\n${row.body}`
}

export class PgSkillStore implements SkillStore {
    private readonly log = createLogger('skill-store')

    // Pass the existing `pg.Pool` for the MAIN PostHog DB (where
    // `llm_analytics_llmskill` lives) — NOT the agent-platform DB. The store
    // does not own connection lifecycle.
    constructor(private readonly pool: Pool) {}

    async resolve(teamId: number, name: string, version?: number, file?: string): Promise<string | null> {
        const { rows } =
            version === undefined
                ? await this.pool.query<SkillRow>(LATEST_SQL, [teamId, name])
                : await this.pool.query<SkillRow>(BY_VERSION_SQL, [teamId, name, version])
        const row = rows[0]
        if (!row) {
            return null
        }
        if (file !== undefined) {
            const result = await this.pool.query<{ content: string }>(FILE_SQL, [row.id, file])
            return result.rows[0]?.content ?? null
        }
        this.log.debug({ team_id: teamId, name, version: row.version, bytes: row.body.length }, 'skill_store.resolved')
        return renderSkillMd(row)
    }
}
