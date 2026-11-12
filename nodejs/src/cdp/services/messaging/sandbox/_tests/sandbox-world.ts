import { randomUUID } from 'crypto'
import { Redis } from 'ioredis'
import { Client } from 'pg'

import { insertIntegration } from '~/cdp/_tests/fixtures'
import { defaultConfig } from '~/common/config/config'
import { deleteKeysWithPrefix } from '~/common/redis/_tests/redis'
import { RedisClient, RedisClientPipeline, RedisV2, createRedisV2PoolFromConfig } from '~/common/redis/redis-v2'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { createRedisFromConfig, createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { PubSub } from '~/common/utils/pubsub'
import { UUIDT } from '~/common/utils/utils'
import { createOrganizationMembership, createTestTeamFixture, createUser } from '~/tests/helpers/sql'
import { RedisPool, Team } from '~/types'

import { RecipientsManagerService } from '../../../managers/recipients-manager.service'
import { RateLimiterService } from '../../../rate-limiter/rate-limiter.service'
import { EmailSuppressionService, emailSuppressionConfigFromEnv } from '../../email-suppression.service'
import { readSandboxAuthorization } from '../sandbox-authorization'
import { SandboxCaps, claimSandboxCaps } from '../sandbox-caps'
import {
    SANDBOX_INTEGRATION_ID,
    SandboxEmailService,
    hasSandboxSenderRow,
    sandboxTeamWorkflowsConfig,
} from '../sandbox-email.service'
import { checkSandboxRecipient, sandboxRecipientReads } from '../sandbox-recipient-checks'
import { SandboxSesBucket } from '../sandbox-ses-bucket'
import { SandboxSesClient, createSandboxSesV2Client } from '../sandbox-ses-client'
import { FakeSesEndpoint } from './fake-ses-endpoint'

const TEST_TABLE_MARK = 'created by the sandbox sender tests'
const TABLES_IN_USE_LOCK = 7_301_001
const TABLES_CREATE_LOCK = 7_301_002

const SANDBOX_SENDER_TABLES = `
    CREATE TABLE IF NOT EXISTS workflows_sandboxsendertenantstate (
        id bigserial PRIMARY KEY,
        tenant_name varchar(64) NOT NULL UNIQUE,
        sending_status varchar(32) NOT NULL DEFAULT '',
        synced_at timestamptz NULL
    );
    CREATE TABLE IF NOT EXISTS workflows_sandboxsenderorganizationblock (
        id bigserial PRIMARY KEY,
        organization_id uuid NOT NULL UNIQUE,
        reason text NOT NULL,
        created_by_id integer NULL,
        created_at timestamptz NOT NULL
    );
    COMMENT ON TABLE workflows_sandboxsendertenantstate IS '${TEST_TABLE_MARK}';
    COMMENT ON TABLE workflows_sandboxsenderorganizationblock IS '${TEST_TABLE_MARK}'`

export const createMissingSandboxSenderTables = async (postgres: PostgresRouter): Promise<() => Promise<void>> => {
    const holder = await postgres.connect(PostgresUse.COMMON_WRITE)
    await holder.query('SELECT pg_advisory_lock_shared($1)', [TABLES_IN_USE_LOCK])
    await holder.query('BEGIN')
    await holder.query('SELECT pg_advisory_xact_lock($1)', [TABLES_CREATE_LOCK])
    const { rows } = await holder.query(
        `SELECT to_regclass('workflows_sandboxsendertenantstate') IS NOT NULL AS present`
    )
    if (!rows[0].present) {
        await holder.query(SANDBOX_SENDER_TABLES)
    }
    await holder.query('COMMIT')
    return async () => {
        try {
            await holder.query('SELECT pg_advisory_unlock_shared($1)', [TABLES_IN_USE_LOCK])
            const { rows: lock } = await holder.query('SELECT pg_try_advisory_lock($1) AS last', [TABLES_IN_USE_LOCK])
            if (lock[0].last) {
                const { rows: mark } = await holder.query(
                    `SELECT obj_description('workflows_sandboxsendertenantstate'::regclass) AS mark`
                )
                if (mark[0]?.mark === TEST_TABLE_MARK) {
                    await holder.query(
                        'DROP TABLE workflows_sandboxsendertenantstate, workflows_sandboxsenderorganizationblock'
                    )
                }
                await holder.query('SELECT pg_advisory_unlock($1)', [TABLES_IN_USE_LOCK])
            }
        } finally {
            holder.release()
        }
    }
}

export const SANDBOX_FROM_ADDRESS = 'sandbox@send.example.com'

export type SandboxFaults = {
    provisioningDb?: PostgresRouter
    authorizationDb?: PostgresRouter
    recipientsDb?: PostgresRouter
    recipientReadTimeoutMs?: number
    teamConfigReadTimeoutMs?: number
    capsLimiter?: RateLimiterService
}

export type SandboxWorld = {
    postgres: PostgresRouter
    valkey: RedisV2
    ses: FakeSesEndpoint
    sesClient: SandboxSesClient
    team: Team
    organizationId: string
    organizationName: string
    tenantName: string
    recipients: RecipientsManagerService
    suppression: EmailSuppressionService
    addMember: (email: string, options?: { verified?: boolean; organizationId?: string }) => Promise<void>
    provision: () => Promise<void>
    setTenant: (sendingStatus: string, syncedAt: Date) => Promise<void>
    blockOrganization: () => Promise<void>
    suspendProjectEmail: () => Promise<void>
    deadPostgres: () => Promise<PostgresRouter>
    lockTable: (table: string) => Promise<() => Promise<void>>
    unreachableLimiter: () => RateLimiterService
    limiter: (name: string) => RateLimiterService
    sesBucket: (capacity: number) => SandboxSesBucket
    takeSlotsLeft: (bucket: SandboxSesBucket) => Promise<number>
    allowanceLeft: (caps: SandboxCaps, storedAddress: string) => Promise<boolean>
    service: (options?: { caps?: SandboxCaps; enabled?: boolean; faults?: SandboxFaults }) => SandboxEmailService
}

export function useSandboxWorld(): SandboxWorld {
    const world = {} as SandboxWorld
    let client: Redis
    let pubSubPool: RedisPool
    let pubSub: PubSub
    let dropCreatedTables: () => Promise<void>

    const write = (sql: string, values: unknown[]) =>
        world.postgres.query(PostgresUse.COMMON_WRITE, sql, values, 'test:sandbox-world')

    beforeAll(async () => {
        world.postgres = new PostgresRouter(defaultConfig)
        dropCreatedTables = await createMissingSandboxSenderTables(world.postgres)
        pubSubPool = createRedisPoolFromConfig({
            connection: { url: defaultConfig.REDIS_URL },
            poolMinSize: 1,
            poolMaxSize: 2,
        })
        pubSub = new PubSub(pubSubPool)
        await pubSub.start()
        client = await createRedisFromConfig(
            defaultConfig.CDP_REDIS_HOST
                ? {
                      url: defaultConfig.CDP_REDIS_HOST,
                      options: { port: defaultConfig.CDP_REDIS_PORT, password: defaultConfig.CDP_REDIS_PASSWORD },
                  }
                : { url: defaultConfig.REDIS_URL }
        )
        world.valkey = {
            useClient: (_options, callback) => callback(client as unknown as RedisClient),
            usePipeline: (_options, callback) => {
                const pipeline = client.pipeline() as unknown as RedisClientPipeline
                callback(pipeline)
                return pipeline.exec()
            },
        }
    })

    afterAll(async () => {
        await dropCreatedTables()
        await pubSub.stop()
        await pubSubPool.drain()
        await pubSubPool.clear()
        await world.postgres.end()
        await client.quit()
    })

    beforeEach(async () => {
        world.ses = new FakeSesEndpoint()
        const endpoint = await world.ses.start()
        world.sesClient = new SandboxSesClient(createSandboxSesV2Client({ region: 'us-east-1', endpoint }), {
            configurationSet: 'sandbox-config-set',
            tenantName: 'sandbox-tenant',
        })
        const fixture = await createTestTeamFixture(world.postgres)
        world.team = fixture.team
        world.organizationId = fixture.organizationId
        const { rows } = await write('SELECT name FROM posthog_organization WHERE id = $1', [world.organizationId])
        world.organizationName = rows[0].name
        world.tenantName = `sandbox-${randomUUID()}`
        world.recipients = new RecipientsManagerService(world.postgres)
        world.suppression = new EmailSuppressionService(world.postgres, emailSuppressionConfigFromEnv())
        await world.provision()
        await world.setTenant('ENABLED', new Date())
    })

    afterEach(async () => {
        await world.ses.stop()
        await deleteKeysWithPrefix(world.valkey, `@posthog/sandbox-email/{${world.organizationId}}/`)
        await deleteKeysWithPrefix(world.valkey, sesBucketKey())
    })

    const sesBucketKey = () => `@posthog/ses/test-${world.team.id}`

    world.addMember = async (email, { verified = true, organizationId } = {}) => {
        const userId = await createUser(world.postgres, new UUIDT().toString())
        await createOrganizationMembership(world.postgres, organizationId ?? world.organizationId, userId)
        await write('UPDATE posthog_user SET email = $1, is_active = true, is_email_verified = $2 WHERE id = $3', [
            email,
            verified,
            userId,
        ])
    }

    world.provision = async () => {
        const sandboxIntegration = {
            kind: 'email_sandbox' as const,
            integration_id: SANDBOX_INTEGRATION_ID,
            config: {},
        }
        await insertIntegration(world.postgres, world.team.id, sandboxIntegration)
    }

    world.setTenant = async (sendingStatus, syncedAt) => {
        await write(
            `INSERT INTO workflows_sandboxsendertenantstate (tenant_name, sending_status, synced_at) VALUES ($1, $2, $3)
             ON CONFLICT (tenant_name) DO UPDATE SET sending_status = EXCLUDED.sending_status, synced_at = EXCLUDED.synced_at`,
            [world.tenantName, sendingStatus, syncedAt]
        )
    }

    world.blockOrganization = async () => {
        await write(
            'INSERT INTO workflows_sandboxsenderorganizationblock (organization_id, reason, created_at) VALUES ($1, $2, NOW())',
            [world.organizationId, 'abuse']
        )
    }

    world.suspendProjectEmail = async () => {
        await write(
            `INSERT INTO workflows_teamworkflowsconfig
                (team_id, capture_workflows_engagement_events, email_tracking_consent_mode,
                 email_sending_suspended_at, email_sending_suspension_reason)
             VALUES ($1, false, 'off', now(), 'sandbox suspension test')
             ON CONFLICT (team_id) DO UPDATE SET email_sending_suspended_at = now()`,
            [world.team.id]
        )
    }

    world.deadPostgres = async () => {
        const router = new PostgresRouter(defaultConfig)
        await router.end()
        return router
    }

    world.lockTable = async (table) => {
        const holder = new Client({ connectionString: defaultConfig.DATABASE_URL })
        holder.on('error', () => undefined)
        await holder.connect()
        await holder.query('BEGIN')
        await holder.query(`SET LOCAL idle_in_transaction_session_timeout = '10s'`)
        await holder.query(`LOCK TABLE ${table} IN ACCESS EXCLUSIVE MODE`)
        return () => holder.end()
    }

    world.unreachableLimiter = () =>
        new RateLimiterService(
            createRedisV2PoolFromConfig({
                connection: {
                    url: '127.0.0.1',
                    options: { port: 1, commandTimeout: 100, retryStrategy: () => null },
                    name: 'sandbox-world-unreachable',
                    exitOnRepeatedErrors: false,
                },
                poolMinSize: 0,
                poolMaxSize: 1,
                acquireTimeoutMillis: 100,
            }),
            { name: 'unreachable' }
        )

    world.limiter = (name) => new RateLimiterService(world.valkey, { name })

    world.sesBucket = (capacity) => ({
        limiter: world.limiter('ses'),
        key: sesBucketKey(),
        capacity,
        refillPerSecond: 0.0001,
    })

    world.takeSlotsLeft = ({ limiter, key, capacity, refillPerSecond }) =>
        limiter.claimUpTo({ key, requested: capacity, capacity, refillPerSecond })

    world.allowanceLeft = async (caps, storedAddress) => {
        const probe = await claimSandboxCaps(world.limiter('sandbox-email-caps'), caps, {
            organizationId: world.organizationId,
            teamId: world.team.id,
            storedAddress,
            claimId: 'allowance probe',
        })
        return probe.ok
    }

    world.service = ({ caps = { team: 5, recipient: 5 }, enabled = true, faults = {} } = {}) => {
        const recipientReads = sandboxRecipientReads(
            faults.recipientsDb ?? world.postgres,
            emailSuppressionConfigFromEnv(),
            faults.recipientReadTimeoutMs
        )
        const limiter = faults.capsLimiter ?? world.limiter('sandbox-email-caps')
        return new SandboxEmailService({
            enabled,
            fromAddress: SANDBOX_FROM_ADDRESS,
            tenantName: world.tenantName,
            isProvisioned: (teamId) => hasSandboxSenderRow(faults.provisioningDb ?? world.postgres, teamId),
            authorize: (request) => readSandboxAuthorization(faults.authorizationDb ?? world.postgres, request),
            checkRecipient: (request) => checkSandboxRecipient(recipientReads, request),
            claimCaps: (claim) => claimSandboxCaps(limiter, caps, claim),
            teamWorkflowsConfig: sandboxTeamWorkflowsConfig(world.postgres, pubSub, faults.teamConfigReadTimeoutMs),
            ses: world.sesClient,
        })
    }

    return world
}
