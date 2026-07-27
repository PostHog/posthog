/**
 * Postgres-backed RevisionStore. Mirrors MemoryRevisionStore's behavior exactly
 * — spec edits only allowed in draft, etc.
 */

import type { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'
import { ZodError } from 'zod'

import { createLogger } from '../runtime/logger'
import {
    AgentApplication,
    AgentRevision,
    AgentRevisionRaw,
    AgentSpec,
    AgentSpecSchema,
    RevisionState,
} from '../spec/spec'
import { NewApplication, NewRevision, RevisionStore } from './revision-store'

const log = createLogger('pg-revision-store')

export class PgRevisionStore implements RevisionStore {
    constructor(private readonly pool: Pool) {}

    async getApplication(applicationId: string): Promise<AgentApplication | null> {
        const r = await this.pool.query(
            `SELECT id, team_id, slug, name, description, live_revision_id, archived
             FROM agent_application WHERE id = $1`,
            [applicationId]
        )
        return r.rowCount === 0 ? null : rowToApp(r.rows[0])
    }

    async getApplicationBySlug(slug: string): Promise<AgentApplication | null> {
        // Global slug namespace — the partial unique index on (slug) where
        // archived = FALSE guarantees at most one row. LIMIT 1 is belt-and-
        // braces against a stray duplicate, never a real disambiguation.
        const r = await this.pool.query(
            `SELECT id, team_id, slug, name, description, live_revision_id, archived
             FROM agent_application WHERE slug = $1 AND archived = FALSE LIMIT 1`,
            [slug]
        )
        return r.rowCount === 0 ? null : rowToApp(r.rows[0])
    }

    async listApplications(teamId: number): Promise<AgentApplication[]> {
        const r = await this.pool.query(
            `SELECT id, team_id, slug, name, description, live_revision_id, archived
             FROM agent_application WHERE team_id = $1 AND archived = FALSE
             ORDER BY created_at ASC`,
            [teamId]
        )
        return r.rows.map(rowToApp)
    }

    async createApplication(input: NewApplication): Promise<AgentApplication> {
        const id = uuidv4()
        await this.pool.query(
            `INSERT INTO agent_application (id, team_id, slug, name, description)
             VALUES ($1, $2, $3, $4, $5)`,
            [id, input.team_id, input.slug, input.name, input.description]
        )
        const r = await this.getApplication(id)
        if (!r) {
            throw new Error('created application not found')
        }
        return r
    }

    async archiveApplication(applicationId: string): Promise<void> {
        await this.pool.query(`UPDATE agent_application SET archived = TRUE, updated_at = NOW() WHERE id = $1`, [
            applicationId,
        ])
    }

    async getRevision(revisionId: string): Promise<AgentRevision | null> {
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec, encrypted_env
             FROM agent_revision WHERE id = $1`,
            [revisionId]
        )
        return r.rowCount === 0 ? null : rowToRev(r.rows[0])
    }

    async getRevisionForApplication(revisionId: string, applicationId: string): Promise<AgentRevision | null> {
        // Tenant-scoped read for request-path callers: the revision must belong
        // to the resolved application, so a leaked/guessed revision id can't
        // resolve another tenant's revision. Returns null on app mismatch.
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec, encrypted_env
             FROM agent_revision WHERE id = $1 AND application_id = $2`,
            [revisionId, applicationId]
        )
        return r.rowCount === 0 ? null : rowToRev(r.rows[0])
    }

    async getRevisionRaw(revisionId: string): Promise<AgentRevisionRaw | null> {
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec, encrypted_env
             FROM agent_revision WHERE id = $1`,
            [revisionId]
        )
        return r.rowCount === 0 ? null : rowToRevRaw(r.rows[0])
    }

    async listRevisions(applicationId: string): Promise<AgentRevision[]> {
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec, encrypted_env
             FROM agent_revision WHERE application_id = $1
             ORDER BY created_at ASC`,
            [applicationId]
        )
        return parseRowsResilient(r.rows)
    }

    async listRevisionsByIdPrefix(applicationId: string, idPrefix: string): Promise<AgentRevision[]> {
        // Strip dashes so the prefix can match the dash-less form (`019e6f25`)
        // or the dashed form (`019e6f25-0185`) — Postgres uuid::text always
        // emits the dashed canonical, so we compare on `replace(id::text, '-', '')`.
        // The functional comparison won't use the PK index but the row count
        // per app is small enough (tens of revs) that a Seq Scan within one
        // application_id is fine.
        const needle = idPrefix.replace(/-/g, '').toLowerCase()
        if (needle.length === 0) {
            return []
        }
        const r = await this.pool.query(
            `SELECT id, application_id, parent_revision_id, created_by_id, created_at, state,
                    bundle_uri, bundle_sha256, spec, encrypted_env
             FROM agent_revision
             WHERE application_id = $1
               AND replace(lower(id::text), '-', '') LIKE $2 || '%'`,
            [applicationId, needle]
        )
        return parseRowsResilient(r.rows)
    }

    async createRevision(input: NewRevision): Promise<AgentRevision> {
        const id = uuidv4()
        await this.pool.query(
            `INSERT INTO agent_revision
                (id, application_id, parent_revision_id, created_by_id, bundle_uri, spec, encrypted_env)
             VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)`,
            [
                id,
                input.application_id,
                input.parent_revision_id,
                input.created_by_id,
                input.bundle_uri,
                JSON.stringify(input.spec),
                input.encrypted_env ?? null,
            ]
        )
        const r = await this.getRevision(id)
        if (!r) {
            throw new Error('created revision not found')
        }
        return r
    }

    async updateSpec(revisionId: string, spec: AgentSpec): Promise<void> {
        // Raw read: this is the write path that fixes a drifted spec — we
        // must not block on parsing the drift we're about to overwrite. The
        // `spec` argument has already been parsed strictly by the caller.
        const cur = await this.getRevisionRaw(revisionId)
        if (!cur) {
            return
        }
        if (cur.state !== 'draft') {
            throw new Error(`revision ${revisionId} is not a draft`)
        }
        await this.pool.query(`UPDATE agent_revision SET spec = $2::jsonb WHERE id = $1`, [
            revisionId,
            JSON.stringify(spec),
        ])
    }

    async setRevisionState(revisionId: string, state: RevisionState, sha256?: string): Promise<void> {
        if (sha256 !== undefined) {
            await this.pool.query(`UPDATE agent_revision SET state = $2, bundle_sha256 = $3 WHERE id = $1`, [
                revisionId,
                state,
                sha256,
            ])
        } else {
            await this.pool.query(`UPDATE agent_revision SET state = $2 WHERE id = $1`, [revisionId, state])
        }
    }

    async setLiveRevision(applicationId: string, revisionId: string): Promise<void> {
        await this.pool.query(`UPDATE agent_application SET live_revision_id = $2, updated_at = NOW() WHERE id = $1`, [
            applicationId,
            revisionId,
        ])
    }

    async listLiveCronRevisions(): Promise<AgentRevision[]> {
        // SQL-side filter on `spec.triggers` would need a JSONB GIN index to be
        // performant; the v0 strategy per plan §6 is in-memory filter over
        // every application's `live_revision_id`. We do JOIN at the SQL layer
        // to avoid a roundtrip-per-app, and let the Node-side filter check
        // `triggers[].type === 'cron'` after deserialisation. Upgrade path:
        // `WHERE spec @> '{"triggers": [{"type": "cron"}]}'::jsonb`
        // paired with a `gin (spec jsonb_path_ops)` index when this query
        // gets hot.
        const r = await this.pool.query(
            `SELECT r.id, r.application_id, r.parent_revision_id, r.created_by_id,
                    r.created_at, r.state, r.bundle_uri, r.bundle_sha256, r.spec, r.encrypted_env
             FROM agent_revision r
             JOIN agent_application a ON a.live_revision_id = r.id
             WHERE a.archived = false`
        )
        // Resilient parse is load-bearing here: this runs every janitor tick
        // across the WHOLE fleet, so a single live spec that no longer parses
        // (e.g. a field the schema later made required) must not throw and
        // abort the entire cron sweep — one poisoned spec would silently stop
        // every agent's cron. `parseRowsResilient` skips + logs the bad row.
        const revs = parseRowsResilient(r.rows)
        return revs.filter((rev) => rev.spec.triggers.some((t) => t.type === 'cron'))
    }
}

function rowToApp(row: {
    id: string
    team_id: number
    slug: string
    name: string
    description: string
    live_revision_id: string | null
    archived: boolean
}): AgentApplication {
    return {
        id: row.id,
        team_id: row.team_id,
        slug: row.slug,
        name: row.name,
        description: row.description,
        live_revision_id: row.live_revision_id,
        archived: row.archived,
    }
}

type RevisionRow = {
    id: string
    application_id: string
    parent_revision_id: string | null
    created_by_id: number | null
    created_at: Date
    state: string
    bundle_uri: string
    bundle_sha256: string | null
    spec: unknown
    encrypted_env: string | null
}

function rowToRev(row: RevisionRow): AgentRevision {
    return {
        ...rowToRevRaw(row),
        spec: AgentSpecSchema.parse(row.spec ?? {}),
    }
}

function rowToRevRaw(row: RevisionRow): AgentRevisionRaw {
    return {
        id: row.id,
        application_id: row.application_id,
        parent_revision_id: row.parent_revision_id,
        created_by_id: row.created_by_id,
        created_at: row.created_at.toISOString(),
        state: row.state as RevisionState,
        bundle_uri: row.bundle_uri,
        bundle_sha256: row.bundle_sha256,
        spec: row.spec ?? {},
        encrypted_env: row.encrypted_env ?? null,
    }
}

/**
 * Parse a revision row, returning `null` instead of throwing when its stored
 * spec no longer satisfies `AgentSpecSchema`. The only way a live row reaches
 * an unparseable state is schema drift — a field the spec schema later made
 * stricter than it was when the revision was frozen. Single-revision reads
 * (`getRevision`) deliberately stay strict so a direct fetch surfaces the real
 * error; this tolerant variant is for the bulk/fleet reads where one bad row
 * must not take out the rest. Exported for unit testing.
 *
 * Only `ZodError` (schema drift) is tolerated — any other throw (a real bug in
 * `rowToRev`, e.g. a null `created_at`) re-raises so it surfaces loudly rather
 * than silently dropping rows across every fleet read.
 */
export function safeRowToRev(row: RevisionRow): AgentRevision | null {
    try {
        return rowToRev(row)
    } catch (err) {
        if (!(err instanceof ZodError)) {
            throw err
        }
        log.warn(
            {
                revision_id: row.id,
                application_id: row.application_id,
                err: err.message,
            },
            'agent.revision.spec_unparseable'
        )
        return null
    }
}

/** Map rows through `safeRowToRev`, dropping (and logging) any that fail to parse. */
function parseRowsResilient(rows: RevisionRow[]): AgentRevision[] {
    const out: AgentRevision[] = []
    for (const row of rows) {
        const rev = safeRowToRev(row)
        if (rev) {
            out.push(rev)
        }
    }
    return out
}
