import { randomUUID } from 'crypto'

import { defaultConfig } from '~/common/config/config'
import { StallingValkeyProxy } from '~/common/redis/_tests/stalling-valkey-proxy'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { UUIDT } from '~/common/utils/utils'
import { waitForExpect } from '~/tests/helpers/expectations'
import {
    createOrganization,
    createOrganizationMembership,
    createTestTeamFixture,
    createUser,
} from '~/tests/helpers/sql'
import { Team } from '~/types'

import { createMissingSandboxSenderTables } from './_tests/sandbox-world'
import {
    MAX_PENDING_AUTHORIZATION_CONNECTIONS,
    readSandboxAuthorization,
    sandboxReadRouter,
} from './sandbox-authorization'

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
        const unavailable = { ok: false, reason: 'authorization_unavailable' }
        let onePoolRouter: PostgresRouter

        const readThrough = (router: PostgresRouter, recipient = memberEmail) =>
            readSandboxAuthorization(router, { teamId: team.id, recipient, tenantName, timeoutMs: 200 })

        beforeEach(() => {
            onePoolRouter = new PostgresRouter({ ...defaultConfig, POSTGRES_CONNECTION_POOL_SIZE: 1 })
        })

        afterEach(async () => {
            await onePoolRouter.end()
        })

        it('refuses at once after enough reads gave up waiting for a connection, until the pool frees one', async () => {
            await createMember(memberEmail, organizationId, true)
            const busy = await sandboxReadRouter(onePoolRouter).connect(PostgresUse.COMMON_WRITE)
            const queued = (): Promise<string> => new Promise((resolve) => setTimeout(resolve, 100, 'queued'))
            try {
                const gaveUp = await Promise.all(
                    Array.from({ length: MAX_PENDING_AUTHORIZATION_CONNECTIONS }, () => readThrough(onePoolRouter))
                )
                expect(gaveUp).toEqual(gaveUp.map(() => unavailable))

                expect(await Promise.race([readThrough(onePoolRouter), queued()])).toEqual(unavailable)
            } finally {
                busy.release()
            }
            ;(await sandboxReadRouter(onePoolRouter).connect(PostgresUse.COMMON_WRITE)).release()

            expect(await readThrough(onePoolRouter)).toMatchObject({ ok: true, storedAddress: memberEmail })
        })

        it('serves a burst of more reads than that limit while the pool keeps answering', async () => {
            await createMember(memberEmail, organizationId, true)

            const burst = await Promise.all(
                Array.from({ length: 3 * MAX_PENDING_AUTHORIZATION_CONNECTIONS }, () =>
                    readSandboxAuthorization(onePoolRouter, {
                        teamId: team.id,
                        recipient: memberEmail,
                        tenantName,
                        timeoutMs: 10_000,
                    })
                )
            )

            expect(burst).toEqual(burst.map(() => expect.objectContaining({ ok: true, storedAddress: memberEmail })))
        })

        it('opens at most that many connections to a database that stops answering a burst of reads, and reads again once new connections answer', async () => {
            await createMember(memberEmail, organizationId, true)
            const database = new URL(defaultConfig.DATABASE_URL)
            const proxy = new StallingValkeyProxy({ host: database.hostname, port: Number(database.port || 5432) })
            database.host = `127.0.0.1:${await proxy.start()}`
            const wide = new PostgresRouter({
                ...defaultConfig,
                DATABASE_URL: database.toString(),
                POSTGRES_CONNECTION_POOL_SIZE: 3 * MAX_PENDING_AUTHORIZATION_CONNECTIONS,
            })
            try {
                proxy.stopAnswering()

                const burst = await Promise.all(
                    Array.from({ length: 3 * MAX_PENDING_AUTHORIZATION_CONNECTIONS }, () => readThrough(wide))
                )

                expect(burst).toEqual(burst.map(() => unavailable))
                expect(proxy.openConnections).toBeLessThanOrEqual(MAX_PENDING_AUTHORIZATION_CONNECTIONS)

                proxy.answerNewConnections()
                await waitForExpect(
                    async () => expect(await readThrough(wide)).toMatchObject({ ok: true, storedAddress: memberEmail }),
                    10_000
                )
            } finally {
                proxy.stop()
                await wide.end()
            }
        })

        it('hands a connection that arrives after the deadline back to the pool', async () => {
            await createMember(memberEmail, organizationId, true)
            const busy = await sandboxReadRouter(onePoolRouter).connect(PostgresUse.COMMON_WRITE)
            expect(await readThrough(onePoolRouter)).toEqual(unavailable)

            busy.release()
            ;(await sandboxReadRouter(onePoolRouter).connect(PostgresUse.COMMON_WRITE)).release()

            expect(await readThrough(onePoolRouter)).toMatchObject({ ok: true, storedAddress: memberEmail })
        })

        it('serves the next read on a clean connection after a query passes the deadline', async () => {
            await createMember(memberEmail, organizationId, true)
            const locker = await postgres.connect(PostgresUse.COMMON_WRITE)
            let locked = false
            try {
                await locker.query('BEGIN')
                await locker.query('LOCK TABLE workflows_sandboxsenderorganizationblock IN ACCESS EXCLUSIVE MODE')
                locked = true

                expect(await readThrough(onePoolRouter)).toEqual(unavailable)
                expect(
                    (
                        await sandboxReadRouter(onePoolRouter).query(
                            PostgresUse.COMMON_WRITE,
                            'SELECT 1 AS answered',
                            undefined,
                            'test:sandbox-authorization-next-read'
                        )
                    ).rows
                ).toEqual([{ answered: 1 }])
                await locker.query('COMMIT')
                locked = false

                expect(await readThrough(onePoolRouter)).toMatchObject({ ok: true, storedAddress: memberEmail })
            } finally {
                if (locked) {
                    await locker.query('COMMIT')
                }
                locker.release()
            }
        })

        it.each([
            [
                'the database refuses connections',
                { DATABASE_URL: 'postgres://posthog:posthog@127.0.0.1:1/posthog' },
                false,
            ],
            ['the router has been ended', {}, true],
        ])('reports authorization as unavailable when %s', async (_case, config, endFirst) => {
            const unreachable = new PostgresRouter({ ...defaultConfig, ...config })
            try {
                if (endFirst) {
                    await unreachable.end()
                }
                expect(await readThrough(unreachable)).toEqual(unavailable)
            } finally {
                if (!endFirst) {
                    await unreachable.end()
                }
            }
        })
    })
})
