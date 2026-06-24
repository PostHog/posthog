import { Pool } from 'pg'

import { AgentSpecSchema, PgRevisionStore } from '@posthog/agent-shared'
import { AgentApplication, AgentRevision } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { AmbiguousRevisionError, RevisionResolver } from './resolver'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
let pool: Pool
beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})
afterAll(async () => {
    await pool.end()
})
beforeEach(async () => {
    await reset({ databaseUrl: TEST_DB_URL })
})

async function seedApp(
    store: PgRevisionStore,
    slug: string,
    teamId = 1
): Promise<{ app: AgentApplication; rev: AgentRevision }> {
    const app = await store.createApplication({ team_id: teamId, slug, name: slug, description: '' })
    const rev = await store.createRevision({
        application_id: app.id,
        parent_revision_id: null,
        created_by_id: null,
        bundle_uri: 's3://x/',
        spec: AgentSpecSchema.parse({ model: 'x' }),
    })
    await store.setRevisionState(rev.id, 'live')
    await store.setLiveRevision(app.id, rev.id)
    return { app, rev }
}

describe('RevisionResolver', () => {
    it('resolves in path mode', async () => {
        const store = new PgRevisionStore(pool)
        const { app } = await seedApp(store, 'weekly-digest')
        const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
        const out = await resolver.resolveFromHostAndPath(undefined, '/agents/weekly-digest/slack/events')
        expect(out!.application.id).toBe(app.id)
    })

    it('resolves in domain mode', async () => {
        const store = new PgRevisionStore(pool)
        await seedApp(store, 'weekly-digest')
        const resolver = new RevisionResolver({
            revisions: store,
            mode: 'domain',
            domainSuffix: '.agents.posthog.com',
        })
        const out = await resolver.resolveFromHostAndPath('weekly-digest.agents.posthog.com', '/slack/events')
        expect(out!.application.slug).toBe('weekly-digest')
    })

    it('resolves a slug regardless of the owning team (global namespace)', async () => {
        // The ingress is no longer single-tenant: a slug owned by any team must
        // resolve, and the resolved app carries that team's real team_id.
        const store = new PgRevisionStore(pool)
        const { app } = await seedApp(store, 'cross-team-agent', 7)
        const resolver = new RevisionResolver({
            revisions: store,
            mode: 'domain',
            domainSuffix: '.agents.posthog.com',
        })
        const out = await resolver.resolveFromHostAndPath('cross-team-agent.agents.posthog.com', '/run')
        expect(out!.application.id).toBe(app.id)
        expect(out!.application.team_id).toBe(7)
    })

    it('returns null for unknown slug', async () => {
        const store = new PgRevisionStore(pool)
        const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
        expect(await resolver.resolveFromHostAndPath(undefined, '/agents/ghost/slack')).toBeNull()
    })

    it('returns null for archived or unlive applications', async () => {
        const store = new PgRevisionStore(pool)
        const { app } = await seedApp(store, 'abandoned')
        await store.archiveApplication(app.id)
        const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
        expect(await resolver.resolveFromHostAndPath(undefined, '/agents/abandoned/x')).toBeNull()
    })

    describe('slug-with-revision-suffix (local-dev form)', () => {
        // PgRevisionStore.createRevision mints a fresh uuid; for slug-suffix
        // tests we want a specific uuid prefix so the regex assertion is
        // deterministic. SQL UPDATE is the simplest way.
        async function rebrandRevisionId(_store: PgRevisionStore, oldId: string, newId: string): Promise<void> {
            await pool.query(`UPDATE agent_revision SET id = $2 WHERE id = $1`, [oldId, newId])
        }

        it('resolves <slug>-<8-hex prefix> to a single revision under that app', async () => {
            const store = new PgRevisionStore(pool)
            const app = await store.createApplication({ team_id: 1, slug: 'preview', name: 'preview', description: '' })
            const rev = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await rebrandRevisionId(store, rev.id, '019e6f25-0185-7814-b4d8-882a429da835')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
            const out = await resolver.resolveBySlug('preview-019e6f25')
            expect(out!.revision.id).toBe('019e6f25-0185-7814-b4d8-882a429da835')
        })

        it('throws AmbiguousRevisionError when the prefix matches multiple revisions', async () => {
            const store = new PgRevisionStore(pool)
            const app = await store.createApplication({ team_id: 1, slug: 'preview', name: 'preview', description: '' })
            const revA = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            const revB = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await rebrandRevisionId(store, revA.id, '019e6f25-0185-7814-b4d8-aaaaaaaaaaaa')
            await rebrandRevisionId(store, revB.id, '019e6f25-0185-7814-b4d8-bbbbbbbbbbbb')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
            await expect(resolver.resolveBySlug('preview-019e6f25')).rejects.toBeInstanceOf(AmbiguousRevisionError)
        })

        it('falls back to verbatim slug when no application has the base slug', async () => {
            const store = new PgRevisionStore(pool)
            // App's slug ends in 8 hex chars but the slug itself is the full string.
            // The 8-hex regex would split as ('unrelated', 'abcdef12'), but there's
            // no app called 'unrelated' — so the resolver falls through to verbatim.
            const app = await store.createApplication({
                team_id: 1,
                slug: 'unrelated-abcdef12',
                name: 'verbatim',
                description: '',
            })
            const rev = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await store.setRevisionState(rev.id, 'live')
            await store.setLiveRevision(app.id, rev.id)
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
            const out = await resolver.resolveBySlug('unrelated-abcdef12')
            expect(out!.application.id).toBe(app.id)
        })

        it('treats archived suffix matches as non-matches (then falls through to verbatim)', async () => {
            const store = new PgRevisionStore(pool)
            const app = await store.createApplication({
                team_id: 1,
                slug: 'with-archived',
                name: 'x',
                description: '',
            })
            const rev = await store.createRevision({
                application_id: app.id,
                parent_revision_id: null,
                created_by_id: null,
                bundle_uri: 's3://x/',
                spec: AgentSpecSchema.parse({ model: 'x' }),
            })
            await rebrandRevisionId(store, rev.id, '019e6f25-0000-0000-0000-000000000000')
            await store.setRevisionState('019e6f25-0000-0000-0000-000000000000', 'archived')
            const resolver = new RevisionResolver({ revisions: store, mode: 'path', pathPrefix: '/agents' })
            // Falls through to verbatim slug, which has no live_revision → null.
            expect(await resolver.resolveBySlug('with-archived-019e6f25')).toBeNull()
        })
    })

    describe('extractSlugFromHost (domain mode)', () => {
        function mkResolver(): RevisionResolver {
            return new RevisionResolver({
                revisions: new PgRevisionStore(pool),
                mode: 'domain',
                domainSuffix: '.agents.posthog.com',
            })
        }

        it('returns the bare slug for a single-label host', () => {
            expect(mkResolver().extractSlugFromHost('weekly-digest.agents.posthog.com')).toBe('weekly-digest')
        })

        it('collapses `<hex>.<slug>` two-label form into the canonical `<slug>-<hex>` shape', () => {
            // Production preview URL form. Reuses the same suffix-matcher the
            // path-mode resolver uses for dev URLs.
            expect(mkResolver().extractSlugFromHost('019e6f25.weekly-digest.agents.posthog.com')).toBe(
                'weekly-digest-019e6f25'
            )
        })

        it('strips the port when present', () => {
            expect(mkResolver().extractSlugFromHost('weekly-digest.agents.posthog.com:8080')).toBe('weekly-digest')
        })

        it('rejects three-label hosts (not a valid shape)', () => {
            expect(mkResolver().extractSlugFromHost('foo.bar.weekly-digest.agents.posthog.com')).toBeNull()
        })

        it('rejects a leading label that is not 8..32 hex', () => {
            // "notahex" doesn't match the prefix shape; refuse rather than
            // silently picking the wrong agent.
            expect(mkResolver().extractSlugFromHost('notahex.weekly-digest.agents.posthog.com')).toBeNull()
        })

        it('returns null for hosts that do not match the suffix', () => {
            expect(mkResolver().extractSlugFromHost('weekly-digest.example.com')).toBeNull()
        })
    })
})
