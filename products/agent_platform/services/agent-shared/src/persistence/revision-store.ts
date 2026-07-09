/**
 * AgentApplication / AgentRevision read+write contract. Production wires to
 * Django via internal HTTP (or direct PG read). The PG impl lives in
 * `pg-revision-store.ts`; there is no in-memory variant — every test goes
 * against the real PG schema under `agent_runtime_queue_test`.
 */

import { AgentApplication, AgentRevision, AgentRevisionRaw, AgentSpec, RevisionState } from '../spec/spec'

export interface RevisionStore {
    getApplication(applicationId: string): Promise<AgentApplication | null>
    /**
     * Resolve a live application by slug across all teams. Slugs are a single
     * global namespace (server-minted on create, globally unique), so domain-
     * mode routing — `<slug>.agents.<suffix>`, which carries no team — can
     * resolve without knowing the team up front. The team is read off the
     * resolved row.
     */
    getApplicationBySlug(slug: string): Promise<AgentApplication | null>
    listApplications(teamId: number): Promise<AgentApplication[]>
    createApplication(input: NewApplication): Promise<AgentApplication>
    archiveApplication(applicationId: string): Promise<void>

    getRevision(revisionId: string): Promise<AgentRevision | null>
    /**
     * Tenant-scoped variant of `getRevision` for request-path callers: only
     * returns the revision when it belongs to `applicationId`. Use this when
     * the revision id came from a caller-influenced source so a leaked id can't
     * resolve another tenant's revision; keep `getRevision` for trusted internal
     * callers (runner session-start, janitor sweep).
     */
    getRevisionForApplication(revisionId: string, applicationId: string): Promise<AgentRevision | null>
    /**
     * Same as `getRevision` but skips `AgentSpecSchema.parse`. For callers
     * that only need state / bundle pointers, or that are about to overwrite
     * the spec wholesale (e.g. `put_bundle`'s merge step). Lets a re-seed
     * recover from schema drift in the source row instead of deadlocking
     * on it.
     */
    getRevisionRaw(revisionId: string): Promise<AgentRevisionRaw | null>
    listRevisions(applicationId: string): Promise<AgentRevision[]>
    /**
     * Resolve revisions on an application whose id starts with the given hex
     * prefix. Used by the ingress resolver to map an ergonomic
     * `<revision-prefix>` URL fragment (e.g. `019e6f25`) to the underlying
     * UUID. Caller decides what to do with collisions — typically refuse the
     * request rather than guess.
     */
    listRevisionsByIdPrefix(applicationId: string, idPrefix: string): Promise<AgentRevision[]>
    createRevision(input: NewRevision): Promise<AgentRevision>
    updateSpec(revisionId: string, spec: AgentSpec): Promise<void>
    setRevisionState(revisionId: string, state: RevisionState, sha256?: string): Promise<void>
    setLiveRevision(applicationId: string, revisionId: string): Promise<void>
    /**
     * List every application's `live_revision_id` whose spec carries at
     * least one cron trigger. Cron tick consumer; runs on the janitor's
     * 30s loop. The v0 PG impl is a single SQL query with a JSONB filter;
     * a JSONB GIN index on `spec->'triggers'` is the upgrade path when
     * cron-enabled live revisions count grows past ~1000.
     */
    listLiveCronRevisions(): Promise<AgentRevision[]>
}

export interface NewApplication {
    team_id: number
    slug: string
    name: string
    description: string
}

export interface NewRevision {
    application_id: string
    parent_revision_id: string | null
    created_by_id: number | null
    bundle_uri: string
    spec: AgentSpec
    /**
     * Optional encrypted env block. Copied forward from a parent revision when
     * forking a new draft so authors don't re-enter secrets per iteration.
     * Omit (or null) for a revision with no secrets.
     */
    encrypted_env?: string | null
}
