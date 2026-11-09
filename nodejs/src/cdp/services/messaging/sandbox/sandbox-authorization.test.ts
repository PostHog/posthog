import { randomUUID } from 'crypto'
import { EventEmitter } from 'events'
import { PoolClient } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import {
    createOrganization,
    createOrganizationMembership,
    createTestTeamFixture,
    createUser,
} from '~/tests/helpers/sql'
import { Team } from '~/types'

import { readSandboxAuthorization } from './sandbox-authorization'

const SANDBOX_SENDER_TABLES = `
    CREATE TABLE workflows_sandboxsendertenantstate (
        id bigserial PRIMARY KEY,
        tenant_name varchar(64) NOT NULL UNIQUE,
        sending_status varchar(32) NOT NULL DEFAULT '',
        synced_at timestamptz NULL
    );
    CREATE TABLE workflows_sandboxsenderorganizationblock (
        id bigserial PRIMARY KEY,
        organization_id uuid NOT NULL UNIQUE,
        reason text NOT NULL,
        created_by_id integer NULL,
        created_at timestamptz NOT NULL
    )`

// The test database gains these tables from the workflows migration once it is on master. Until then the test
// creates them, and drops them again so a later migrate can still create them.
const createMissingSandboxSenderTables = async (postgres: PostgresRouter): Promise<() => Promise<void>> => {
    const { rows } = await postgres.query(
        PostgresUse.COMMON_WRITE,
        `SELECT to_regclass('workflows_sandboxsendertenantstate') IS NOT NULL AS present`,
        undefined,
        'test:find-sandbox-sender-tables'
    )
    if (rows[0].present) {
        return () => Promise.resolve()
    }
    await postgres.query(
        PostgresUse.COMMON_WRITE,
        SANDBOX_SENDER_TABLES,
        undefined,
        'test:create-sandbox-sender-tables'
    )
    return async () => {
        await postgres.query(
            PostgresUse.COMMON_WRITE,
            'DROP TABLE workflows_sandboxsendertenantstate, workflows_sandboxsenderorganizationblock',
            undefined,
            'test:drop-sandbox-sender-tables'
        )
    }
}

describe('readSandboxAuthorization', () => {
    let postgres: PostgresRouter
    let team: Team
    let organizationId: string
    let tenantName: string
    let memberEmail: string
    let dropCreatedTables: () => Promise<void>

    const write = (sql: string, values: unknown[]) =>
        postgres.query(PostgresUse.COMMON_WRITE, sql, values, 'test:sandbox-authorization')

    const createMember = async (email: string, inOrganization: string, verified: boolean | null): Promise<number> => {
        const userId = await createUser(postgres, new UUIDT().toString())
        await createOrganizationMembership(postgres, inOrganization, userId)
        await write('UPDATE posthog_user SET email = $1, is_active = true, is_email_verified = $2 WHERE id = $3', [
            email,
            verified,
            userId,
        ])
        return userId
    }

    const read = (recipient: string, teamId = team.id) =>
        readSandboxAuthorization(postgres, { teamId, recipient, tenantName })

    beforeAll(async () => {
        postgres = new PostgresRouter(defaultConfig)
        dropCreatedTables = await createMissingSandboxSenderTables(postgres)
    })

    afterAll(async () => {
        await dropCreatedTables()
        await postgres.end()
    })

    beforeEach(async () => {
        ;({ team, organizationId } = await createTestTeamFixture(postgres))
        tenantName = `sandbox-${randomUUID()}`
        memberEmail = `member-${team.id}@example.com`
    })

    it('authorizes a verified member at their stored address, with the organization and tenant mirror', async () => {
        await createMember(memberEmail, organizationId, true)
        const syncedAt = new Date('2026-01-01T12:00:00Z')
        await write(
            'INSERT INTO workflows_sandboxsendertenantstate (tenant_name, sending_status, synced_at) VALUES ($1, $2, $3)',
            [tenantName, 'ENABLED', syncedAt]
        )
        const { rows } = await write('SELECT name FROM posthog_organization WHERE id = $1', [organizationId])

        expect(await read(`  ${memberEmail.toUpperCase()} `)).toEqual({
            ok: true,
            organizationId,
            organizationName: rows[0].name,
            storedAddress: memberEmail,
            tenant: { sendingStatus: 'ENABLED', syncedAt },
        })
    })

    it('reads a missing tenant mirror as unknown', async () => {
        await createMember(memberEmail, organizationId, true)

        expect(await read(memberEmail)).toMatchObject({ ok: true, tenant: { sendingStatus: null, syncedAt: null } })
    })

    it.each<[string, boolean | null, (userId: number) => Promise<unknown>]>([
        ['an unverified member', false, () => Promise.resolve()],
        ['a member with no recorded verification', null, () => Promise.resolve()],
        [
            'a removed member',
            true,
            (userId) => write('DELETE FROM posthog_organizationmembership WHERE user_id = $1', [userId]),
        ],
        [
            'a deactivated user',
            true,
            (userId) => write('UPDATE posthog_user SET is_active = false WHERE id = $1', [userId]),
        ],
        [
            'a member of an inactive organization',
            true,
            () => write('UPDATE posthog_organization SET is_active = false WHERE id = $1', [organizationId]),
        ],
    ])('refuses %s', async (_case, verified, change) => {
        await change(await createMember(memberEmail, organizationId, verified))

        expect(await read(memberEmail)).toEqual({ ok: false, reason: 'not_member' })
    })

    it('refuses a verified member of another organization', async () => {
        const outsider = `outsider-${team.id}@example.com`
        await createMember(outsider, await createOrganization(postgres), true)

        expect(await read(outsider)).toEqual({ ok: false, reason: 'not_member' })
    })

    it.each([
        [
            'delivers to the stored spelling that matches exactly',
            ['Member', 'member'],
            'Member',
            { ok: true, storedAddress: 'Member' },
        ],
        [
            'refuses a spelling that matches neither',
            ['Member', 'member'],
            'MEMBER',
            { ok: false, reason: 'ambiguous_member' },
        ],
        [
            'delivers to the one address when padding is all they differ by',
            ['member', ' member'],
            'MEMBER',
            { ok: true, storedAddress: 'member' },
        ],
    ])('%s of two members whose stored addresses differ only in case', async (_case, stored, written, expected) => {
        for (const name of stored) {
            await createMember(`${name}-${team.id}@example.com`, organizationId, true)
        }
        const suffix = `-${team.id}@example.com`

        const authorization = await read(`${written}${suffix}`)

        expect(authorization).toMatchObject(
            'storedAddress' in expected
                ? { ...expected, storedAddress: `${expected.storedAddress}${suffix}` }
                : expected
        )
    })

    it('refuses every recipient of a blocked organization', async () => {
        await createMember(memberEmail, organizationId, true)
        await write(
            'INSERT INTO workflows_sandboxsenderorganizationblock (organization_id, reason, created_at) VALUES ($1, $2, now())',
            [organizationId, 'abuse']
        )

        expect(await read(memberEmail)).toEqual({ ok: false, reason: 'organization_blocked' })
    })

    it('reports a team that does not exist', async () => {
        expect(await read(memberEmail, 2_000_000_001)).toEqual({ ok: false, reason: 'team_not_found' })
    })

    describe('when the database stalls', () => {
        type FakeClient = EventEmitter & { query: jest.Mock; release: jest.Mock }

        const stalledRouter = (
            connect: () => Promise<FakeClient>
        ): { router: PostgresRouter; clients: FakeClient[] } => {
            const router = new PostgresRouter({ DATABASE_URL: 'postgres://fake', POSTGRES_CONNECTION_POOL_SIZE: 1 })
            const clients: FakeClient[] = []
            jest.spyOn(router, 'connect').mockImplementation(() =>
                connect().then((client) => {
                    clients.push(client)
                    return client as unknown as PoolClient
                })
            )
            return { router, clients }
        }
        const fakeClient = (query: () => Promise<unknown>): FakeClient =>
            Object.assign(new EventEmitter(), { query: jest.fn(query), release: jest.fn() })

        beforeEach(() => jest.useFakeTimers())
        afterEach(() => jest.useRealTimers())

        it('reports authorization as unavailable when no connection is free, and runs no SQL on one handed over late', async () => {
            let handOver: () => void = () => undefined
            const late = fakeClient(() => Promise.resolve({ rows: [] }))
            const { router, clients } = stalledRouter(
                () => new Promise<FakeClient>((resolve) => (handOver = () => resolve(late)))
            )

            const authorization = readSandboxAuthorization(router, { teamId: 1, recipient: memberEmail, tenantName })
            await jest.advanceTimersByTimeAsync(2_000)
            expect(await authorization).toEqual({ ok: false, reason: 'authorization_unavailable' })

            handOver()
            await jest.advanceTimersByTimeAsync(0)
            expect(clients).toEqual([late])
            expect(late.query).not.toHaveBeenCalled()
            expect(late.release.mock.calls).toEqual([[]])
        })

        it('reports authorization as unavailable when a query stalls, and destroys that connection', async () => {
            const stalled = fakeClient(() => new Promise<never>(() => undefined))
            const { router } = stalledRouter(() => Promise.resolve(stalled))

            const authorization = readSandboxAuthorization(router, { teamId: 1, recipient: memberEmail, tenantName })
            await jest.advanceTimersByTimeAsync(2_000)

            expect(await authorization).toEqual({ ok: false, reason: 'authorization_unavailable' })
            expect(stalled.release).toHaveBeenCalledWith(expect.any(Error))
        })

        it('reports authorization as unavailable when connecting fails', async () => {
            const { router } = stalledRouter(() => Promise.reject(new Error('connection refused')))

            expect(await readSandboxAuthorization(router, { teamId: 1, recipient: memberEmail, tenantName })).toEqual({
                ok: false,
                reason: 'authorization_unavailable',
            })
        })
    })
})
