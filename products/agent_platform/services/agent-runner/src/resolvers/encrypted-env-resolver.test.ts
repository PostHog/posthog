import { Pool } from 'pg'

import { AgentSpecSchema, EMPTY_USAGE_TOTAL, EncryptedFields, PgRevisionStore } from '@posthog/agent-shared'
import { reset } from '@posthog/agent-shared/testing'

import { makeEncryptedEnvResolver } from './encrypted-env-resolver'

const TEST_DB_URL =
    process.env.AGENT_TEST_DB_URL ?? 'postgres://posthog:posthog@localhost:5432/agent_runtime_queue_test'
let pool: Pool
beforeAll(() => {
    pool = new Pool({ connectionString: TEST_DB_URL })
})
afterAll(async () => {
    await pool.end()
})

const KEY = '01234567890123456789012345678901'

function freshSession(overrides: Record<string, unknown> = {}): never {
    return {
        id: 's1',
        application_id: 'app1',
        revision_id: 'rev1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'queued',
        principal: null,
        conversation: [],
        pending_inputs: [],
        retry_count: 0,
        usage_total: { ...EMPTY_USAGE_TOTAL },
        acl: [],
        pending_elevation_requests: [],
        created_at: '2026-05-27',
        updated_at: '2026-05-27',
        ...overrides,
    } as never
}

describe('makeEncryptedEnvResolver', () => {
    let revisions: PgRevisionStore
    let encryption: EncryptedFields

    beforeEach(async () => {
        await reset({ databaseUrl: TEST_DB_URL })
        revisions = new PgRevisionStore(pool)
        encryption = new EncryptedFields(KEY)
    })

    // Seed an application + a revision carrying `encrypted_env`. Secrets live on
    // the REVISION now, so the resolver reads them off `session.revision_id`.
    // Returns the revision id to stamp onto the session under test.
    async function seedRevision(encryptedEnv: string | null): Promise<string> {
        const app = await revisions.createApplication({
            team_id: 1,
            slug: 'a',
            name: 'A',
            description: '',
        })
        const rev = await revisions.createRevision({
            application_id: app.id,
            parent_revision_id: null,
            created_by_id: null,
            bundle_uri: 's3://x/',
            spec: AgentSpecSchema.parse({ model: 'test/x' }),
            encrypted_env: encryptedEnv,
        })
        return rev.id
    }

    it('returns {} when no encrypted_env is set on the revision', async () => {
        const revId = await seedRevision(null)
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ revision_id: revId }))).toEqual({})
    })

    it('returns {} when the revision is unknown (revision_store returns null)', async () => {
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ revision_id: '00000000-0000-4000-8000-000000000666' }))).toEqual({})
    })

    it("decrypts the revision's JSON env block into a string-only map", async () => {
        const ct = encryption.encrypt(JSON.stringify({ STRIPE_KEY: 'sk_test_x', PORT: 8080 }))
        const revId = await seedRevision(ct)
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ revision_id: revId }))).toEqual({
            STRIPE_KEY: 'sk_test_x',
            PORT: '8080',
        })
    })

    it('returns {} (not throw) when decryption fails — keeps the session alive', async () => {
        const otherKey = new EncryptedFields('AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA')
        const ct = otherKey.encrypt(JSON.stringify({ X: 'y' }))
        const revId = await seedRevision(ct)
        const resolve = makeEncryptedEnvResolver({ revisions, encryption })
        expect(await resolve(freshSession({ revision_id: revId }))).toEqual({})
    })
})
