import { Client } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { createTeam, createTestTeamFixture } from '~/tests/helpers/sql'
import { INVALID_TEAM_ID_KEYS } from '~/tests/helpers/team'
import { Hub, Team } from '~/types'

import {
    EmailSuppressionService,
    SuppressionLookupError,
    emailSuppressionConfigFromEnv,
} from './email-suppression.service'

interface SuppressionRow {
    identifier: string
    source: string
    suppressed: boolean
    transient_bounce_count: number
    last_bounce_diagnostic: string | null
    deleted: boolean
}

describe('EmailSuppressionService', () => {
    let hub: Hub
    let team: Team
    let originalThresholdEnv: string | undefined

    beforeEach(async () => {
        hub = await createHub()
        team = (await createTestTeamFixture(hub.postgres)).team
        originalThresholdEnv = process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD
    })

    afterEach(async () => {
        if (originalThresholdEnv === undefined) {
            delete process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD
        } else {
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = originalThresholdEnv
        }
        await closeHub(hub)
    })

    const readRow = async (email: string): Promise<SuppressionRow | undefined> => {
        const res = await hub.postgres.query<SuppressionRow>(
            PostgresUse.COMMON_READ,
            `SELECT identifier, source, suppressed, transient_bounce_count, last_bounce_diagnostic, deleted
             FROM posthog_messagesuppression
             WHERE team_id = $1 AND identifier = $2`,
            [team.id, email],
            'test-read-suppression'
        )
        return res.rows[0]
    }

    describe('recordTransientBounces (threshold=3)', () => {
        beforeEach(() => {
            // Threshold=3 gives a clean boundary: 2 bounces must not flip, 3 must.
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '3'
        })

        it.each([
            ['below threshold — 2 consecutive bounces stay unsuppressed', 2, false],
            ['at threshold — the 3rd consecutive bounce flips suppressed', 3, true],
        ] as const)('%s', async (_label, bounces, expectedSuppressed) => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'flaky@example.com'
            for (let i = 0; i < bounces; i++) {
                await svc.recordTransientBounces(team.id, [email], 'temp')
            }
            expect(await readRow(email)).toMatchObject({
                identifier: email,
                source: 'BOUNCE',
                transient_bounce_count: bounces,
                suppressed: expectedSuppressed,
                deleted: false,
            })
        })
    })

    describe('recordDeliveries', () => {
        beforeEach(() => {
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '5'
        })

        it('resets the counter after a successful delivery so a transient outage does not accumulate', async () => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'temporarily-unreachable@example.com'

            await svc.recordTransientBounces(team.id, [email], 'temp')
            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect((await readRow(email))?.transient_bounce_count).toBe(2)

            // Newer delivery timestamp than the just-recorded bounces.
            const newerTimestamp = new Date(Date.now() + 60 * 1000).toISOString()
            await svc.recordDeliveries(team.id, [email], newerTimestamp)
            expect(await readRow(email)).toMatchObject({
                transient_bounce_count: 0,
                suppressed: false,
            })
        })

        it('does not reset the counter when the delivery is missing a timestamp (fail closed)', async () => {
            // Guards against a caller that forgets to pass the delivery timestamp — without one we
            // can't prove the delivery is newer than the last bounce, so we leave the counter alone.
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'no-timestamp@example.com'

            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect((await readRow(email))?.transient_bounce_count).toBe(1)

            await svc.recordDeliveries(team.id, [email])
            expect((await readRow(email))?.transient_bounce_count).toBe(1)
        })

        it('ignores a delivery older than the last bounce (out-of-order events)', async () => {
            // Guards against SES delivery + bounce notifications for different sends arriving in any
            // order — a late delivery for an older send must not erase a fresh bounce.
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'flaky@example.com'

            await svc.recordTransientBounces(team.id, [email], 'temp')
            const rowAfterBounce = await readRow(email)
            expect(rowAfterBounce?.transient_bounce_count).toBe(1)

            // Delivery timestamp is 1 hour before the bounce we just recorded.
            const olderTimestamp = new Date(Date.now() - 60 * 60 * 1000).toISOString()
            await svc.recordDeliveries(team.id, [email], olderTimestamp)

            expect((await readRow(email))?.transient_bounce_count).toBe(1)
        })

        it('resets the counter when the delivery is newer than the last bounce', async () => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'legit-recovering@example.com'

            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect((await readRow(email))?.transient_bounce_count).toBe(1)

            const futureTimestamp = new Date(Date.now() + 60 * 60 * 1000).toISOString()
            await svc.recordDeliveries(team.id, [email], futureTimestamp)

            expect((await readRow(email))?.transient_bounce_count).toBe(0)
        })

        it.each([
            [
                'an old bounce, then the delivery that followed it, resets',
                [
                    ['bounce', 2],
                    ['delivery', 1],
                ],
                0,
                'temp 2',
                true,
            ],
            [
                'a team outside the allowlist stamps the write time, so the older delivery does not reset',
                [
                    ['bounce', 2],
                    ['delivery', 1],
                ],
                1,
                'temp 2',
                false,
            ],
            [
                'a late bounce does not move the last bounce back, so an older delivery cannot reset',
                [
                    ['bounce', 1],
                    ['bounce', 3],
                    ['delivery', 2],
                ],
                2,
                'temp 1',
                true,
            ],
            [
                'a bounce without a parseable time falls back to now',
                [
                    ['bounce', 'not-a-timestamp'],
                    ['delivery', 1],
                ],
                1,
                'temp not-a-timestamp',
                true,
            ],
        ] as const)('%s', async (_label, events, expectedCount, expectedDiagnostic, teamUsesEventTime) => {
            const svc = new EmailSuppressionService(hub.postgres, {
                ...emailSuppressionConfigFromEnv(),
                softBounceEventTimeTeams: teamUsesEventTime ? String(team.id) : '',
            })
            const email = 'replayed@example.com'
            const hoursAgo = (offset: number | string): string =>
                typeof offset === 'string' ? offset : new Date(Date.now() - offset * 60 * 60 * 1000).toISOString()

            for (const [kind, offset] of events) {
                if (kind === 'bounce') {
                    await svc.recordTransientBounces(team.id, [email], `temp ${offset}`, hoursAgo(offset))
                } else {
                    await svc.recordDeliveries(team.id, [email], hoursAgo(offset))
                }
            }

            expect(await readRow(email)).toMatchObject({
                transient_bounce_count: expectedCount,
                last_bounce_diagnostic: expectedDiagnostic,
            })
        })
    })

    describe('recordHardBounces', () => {
        beforeEach(() => {
            // Threshold irrelevant — hard bounces suppress on the first hit.
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '5'
        })

        it('suppresses immediately with source=BOUNCE and the diagnostic captured', async () => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'permanent-fail@example.com'
            await svc.recordHardBounces(team.id, [email], 'smtp; 550 5.1.1 user unknown')

            expect(await readRow(email)).toMatchObject({
                identifier: email,
                source: 'BOUNCE',
                suppressed: true,
                transient_bounce_count: 0,
                deleted: false,
            })
        })

        it('escalates an unsuppressed BOUNCE counter to suppressed when a hard bounce lands', async () => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'escalating@example.com'
            // Two soft bounces — below threshold, still unsuppressed.
            await svc.recordTransientBounces(team.id, [email], 'temp')
            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect(await readRow(email)).toMatchObject({ suppressed: false, transient_bounce_count: 2 })

            await svc.recordHardBounces(team.id, [email], 'smtp; 550 5.1.1 user unknown')
            expect(await readRow(email)).toMatchObject({
                suppressed: true,
                // Counter is history; we keep it. Hard bounce is now the operative reason.
                transient_bounce_count: 2,
            })
        })

        it('does not override a MANUAL entry (user-managed rows are authoritative)', async () => {
            const email = 'user-managed@example.com'
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagesuppression
                    (id, team_id, identifier, source, reason, transient_bounce_count,
                     suppressed, suppressed_at, deleted, created_at, updated_at)
                 VALUES (gen_random_uuid(), $1, $2, 'MANUAL', 'Manually added', 0,
                     true, NOW(), false, NOW(), NOW())`,
                [team.id, email],
                'test-insert-manual'
            )

            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            await svc.recordHardBounces(team.id, [email], 'smtp; 550 5.1.1 user unknown')

            expect(await readRow(email)).toMatchObject({
                source: 'MANUAL',
                suppressed: true,
            })
            // The reason must not be overwritten to the auto-suppressed one.
            const detail = await hub.postgres.query<{ reason: string }>(
                PostgresUse.COMMON_READ,
                `SELECT reason FROM posthog_messagesuppression WHERE team_id = $1 AND identifier = $2`,
                [team.id, email],
                'test-read-reason'
            )
            expect(detail.rows[0].reason).toBe('Manually added')
        })
    })

    describe('recordComplaints', () => {
        it('suppresses immediately with source=COMPLAINT and the feedback type in the reason', async () => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'reporter@example.com'
            await svc.recordComplaints(team.id, [email], 'abuse')

            expect(await readRow(email)).toMatchObject({
                identifier: email,
                source: 'COMPLAINT',
                suppressed: true,
                transient_bounce_count: 0,
                deleted: false,
            })
            const detail = await hub.postgres.query<{ reason: string }>(
                PostgresUse.COMMON_READ,
                `SELECT reason FROM posthog_messagesuppression WHERE team_id = $1 AND identifier = $2`,
                [team.id, email],
                'test-read-complaint-reason'
            )
            expect(detail.rows[0].reason).toBe('Auto-suppressed after a spam complaint (feedback type: abuse)')
        })

        it('re-keys an unsuppressed BOUNCE counter to COMPLAINT when a complaint lands', async () => {
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '5'
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'bounced-then-reported@example.com'
            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect(await readRow(email)).toMatchObject({ source: 'BOUNCE', suppressed: false })

            await svc.recordComplaints(team.id, [email])
            expect(await readRow(email)).toMatchObject({
                source: 'COMPLAINT',
                suppressed: true,
                // Counter is history; we keep it. The complaint is now the operative reason.
                transient_bounce_count: 1,
            })
        })

        it('does not override a MANUAL entry (user-managed rows are authoritative)', async () => {
            const email = 'user-managed@example.com'
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagesuppression
                    (id, team_id, identifier, source, reason, transient_bounce_count,
                     suppressed, suppressed_at, deleted, created_at, updated_at)
                 VALUES (gen_random_uuid(), $1, $2, 'MANUAL', 'Manually added', 0,
                     true, NOW(), false, NOW(), NOW())`,
                [team.id, email],
                'test-insert-manual'
            )

            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            await svc.recordComplaints(team.id, [email], 'abuse')

            expect(await readRow(email)).toMatchObject({ source: 'MANUAL', suppressed: true })
            const detail = await hub.postgres.query<{ reason: string }>(
                PostgresUse.COMMON_READ,
                `SELECT reason FROM posthog_messagesuppression WHERE team_id = $1 AND identifier = $2`,
                [team.id, email],
                'test-read-reason'
            )
            expect(detail.rows[0].reason).toBe('Manually added')
        })

        it.each(['hard', 'transient'] as const)(
            'keeps source and reason on a complaint row when a later %s bounce lands',
            async (bounceType) => {
                // Threshold=1 so one soft bounce crosses it. Above 1 the transient path never
                // reaches the branch that rewrites the reason, and the case would prove nothing.
                process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '1'
                const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
                const email = `complained-then-${bounceType}@example.com`
                const diagnostic = 'smtp; 550 5.1.1 user unknown'

                await svc.recordComplaints(team.id, [email], 'abuse')
                await (bounceType === 'hard'
                    ? svc.recordHardBounces(team.id, [email], diagnostic)
                    : svc.recordTransientBounces(team.id, [email], diagnostic))

                expect(await readRow(email)).toMatchObject({ source: 'COMPLAINT', suppressed: true })
                const detail = await hub.postgres.query<{ reason: string; last_bounce_diagnostic: string }>(
                    PostgresUse.COMMON_READ,
                    `SELECT reason, last_bounce_diagnostic FROM posthog_messagesuppression
                     WHERE team_id = $1 AND identifier = $2`,
                    [team.id, email],
                    'test-read-complaint-then-bounce'
                )
                // Without the precedence the row would read as a bounce suppression while still
                // tagged COMPLAINT.
                expect(detail.rows[0].reason).toBe('Auto-suppressed after a spam complaint (feedback type: abuse)')
                // The bounce is still recorded, just not as the row's headline reason.
                expect(detail.rows[0].last_bounce_diagnostic).toBe(diagnostic)
            }
        )
    })

    describe('transactional email to a suppressed address', () => {
        it.each([
            ['a complaint alone lets it through', ['complaint'], false],
            ['soft bounces up to the threshold let it through', ['soft', 'soft', 'soft'], false],
            ['soft bounces after a complaint let it through', ['complaint', 'soft', 'soft', 'soft'], false],
            ['a hard bounce blocks it', ['hard'], true],
            ['a hard bounce after the complaint blocks it', ['complaint', 'hard'], true],
            ['a hard bounce before the complaint blocks it', ['hard', 'complaint'], true],
            ['a hard bounce after soft bounces blocks it', ['soft', 'soft', 'soft', 'hard'], true],
            ['a hard bounce on a manual entry blocks it', ['manual', 'hard'], true],
            ['a complaint after a legacy hard bounce still blocks it', ['legacy-hard', 'complaint'], true],
            ['soft bounces after a legacy hard bounce still block it', ['legacy-hard', 'soft', 'soft', 'soft'], true],
        ] as const)('%s', async (_label, steps, blocked) => {
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '3'
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'suppressed@example.com'

            for (const step of steps) {
                if (step === 'manual') {
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        `INSERT INTO posthog_messagesuppression
                            (id, team_id, identifier, source, reason, transient_bounce_count,
                             suppressed, suppressed_at, deleted, created_at, updated_at)
                         VALUES (gen_random_uuid(), $1, $2, 'MANUAL', 'test row', 0,
                             true, NOW(), false, NOW(), NOW())`,
                        [team.id, email],
                        'test-insert-manual-suppression'
                    )
                } else if (step === 'legacy-hard') {
                    // A row written before `hard_bounced_at` existed: the mark is only in the reason.
                    await hub.postgres.query(
                        PostgresUse.COMMON_WRITE,
                        `INSERT INTO posthog_messagesuppression
                            (id, team_id, identifier, source, reason, transient_bounce_count,
                             suppressed, suppressed_at, deleted, created_at, updated_at)
                         VALUES (gen_random_uuid(), $1, $2, 'BOUNCE', 'Auto-suppressed after a hard bounce', 0,
                             true, NOW(), false, NOW(), NOW())`,
                        [team.id, email],
                        'test-insert-legacy-hard-suppression'
                    )
                } else if (step === 'complaint') {
                    await svc.recordComplaints(team.id, [email], 'abuse')
                } else if (step === 'hard') {
                    await svc.recordHardBounces(team.id, [email], 'smtp; 550 5.1.1 user unknown')
                } else if (step === 'soft') {
                    await svc.recordTransientBounces(team.id, [email], 'smtp; 421 try again later')
                } else {
                    // Bounces stamp last_bounce_at with NOW(), so a delivery has to be newer than that.
                    await svc.recordDeliveries(team.id, [email], new Date(Date.now() + 60_000).toISOString())
                }
            }

            expect(await svc.isSuppressed(team.id, email, { transactional: true })).toBe(blocked)
            expect(await svc.isSuppressed(team.id, email)).toBe(true)
        })
    })

    describe('global hard-bounce list', () => {
        const newService = (globalHardBounceEnforce: boolean): EmailSuppressionService =>
            new EmailSuppressionService(hub.postgres, { ...emailSuppressionConfigFromEnv(), globalHardBounceEnforce })

        // The list is instance-global and outlives each test's team, so every test uses its own address.
        const bounceForAnotherTeam = async (email: string): Promise<number> => {
            const otherTeamId = await createTeam(hub.postgres, team.organization_id)
            const svc = newService(true)
            await svc.recordHardBounces(otherTeamId, [email], 'smtp; 550 5.1.1 user unknown')
            await svc.recordGlobalHardBounces([email])
            return otherTeamId
        }

        it.each([
            ['shadow', false, false, undefined],
            ['enforce', true, true, 'BOUNCE'],
        ] as const)(
            'in %s mode, another team bouncing the address blocks it: %s',
            async (mode, enforce, blocked, source) => {
                const email = `gone-${mode}-${team.id}@example.com`
                await bounceForAnotherTeam(email)

                const svc = newService(enforce)
                expect(await svc.isSuppressed(team.id, email, { transactional: true })).toBe(blocked)
                expect((await readRow(email))?.source).toBe(source)
            }
        )

        it.each([
            ['the team removed the address', 'removed'],
            ['a later delivery cleared the entry', 'delivered'],
        ] as const)('does not block when %s', async (_label, step) => {
            const email = `back-${step}-${team.id}@example.com`
            const otherTeamId = await bounceForAnotherTeam(email)

            if (step === 'removed') {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_messagesuppression
                        (id, team_id, identifier, source, reason, transient_bounce_count,
                         suppressed, suppressed_at, deleted, created_at, updated_at)
                     VALUES (gen_random_uuid(), $1, $2, 'BOUNCE', NULL, 0, false, NULL, true, NOW(), NOW())`,
                    [team.id, email],
                    'test-insert-removed-suppression'
                )
            } else {
                // Bounces stamp last_bounced_at with NOW(), so a delivery has to be newer than that.
                await newService(true).recordDeliveries(
                    otherTeamId,
                    [email],
                    new Date(Date.now() + 60_000).toISOString(),
                    {
                        clearGlobal: true,
                    }
                )
            }

            expect(await newService(true).isSuppressed(team.id, email)).toBe(false)
        })

        it.each([
            ['shadow', false],
            ['enforce', true],
        ] as const)(
            'in %s mode, a global list read that times out holds the send until a retry reads the list: %s',
            async (mode, enforce) => {
                const email = `unread-${mode}-${team.id}@example.com`
                await bounceForAnotherTeam(email)
                const databaseUrl = new URL(defaultConfig.DATABASE_URL)
                databaseUrl.searchParams.set('options', '-c lock_timeout=100')
                const reader = new PostgresRouter({
                    ...defaultConfig,
                    DATABASE_URL: databaseUrl.toString(),
                    DATABASE_READONLY_URL: '',
                })
                const service = new EmailSuppressionService(reader, {
                    ...emailSuppressionConfigFromEnv(),
                    globalHardBounceEnforce: enforce,
                })
                const lockHolder = new Client({ connectionString: defaultConfig.DATABASE_URL })
                lockHolder.on('error', () => undefined)
                await lockHolder.connect()
                try {
                    await lockHolder.query('BEGIN')
                    await lockHolder.query(`SET LOCAL idle_in_transaction_session_timeout = '10s'`)
                    await lockHolder.query('LOCK TABLE posthog_emailhardbounce IN ACCESS EXCLUSIVE MODE')

                    const lookup = service.isSuppressed(team.id, email, { transactional: true })
                    if (enforce) {
                        await expect(lookup).rejects.toBeInstanceOf(SuppressionLookupError)
                    } else {
                        await expect(lookup).resolves.toBe(false)
                    }

                    await lockHolder.query('COMMIT')
                    expect(await service.isSuppressed(team.id, email, { transactional: true })).toBe(enforce)
                } finally {
                    await lockHolder.end()
                    await reader.end()
                }
            }
        )

        it.each([
            ['bounced once, an hour ago', 1 / 24, 1 / 24, true],
            ['bounced once, two days ago', 2, 2, false],
            ['bounced for ten days, last five days ago', 15, 5, true],
            ['bounced for two months, last fifteen days ago', 75, 15, false],
        ] as const)(
            'holds an entry for as long as the address has been bouncing, up to 14 days: %s',
            async (_label, firstDaysAgo, lastDaysAgo, blocked) => {
                const email = `held-${firstDaysAgo}-${lastDaysAgo}-${team.id}@example.com`
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_emailhardbounce (email, first_bounced_at, last_bounced_at)
                     VALUES ($1, NOW() - $2 * INTERVAL '1 day', NOW() - $3 * INTERVAL '1 day')`,
                    [email, firstDaysAgo, lastDaysAgo],
                    'test-insert-global-hard-bounce'
                )

                expect(await newService(true).isSuppressed(team.id, email, { transactional: true })).toBe(blocked)
            }
        )

        it("blocks transactional email when the team's own entry only blocks other email", async () => {
            const email = `complained-${team.id}@example.com`
            await bounceForAnotherTeam(email)
            const svc = newService(true)
            await svc.recordComplaints(team.id, [email], 'abuse')

            expect(await svc.isSuppressed(team.id, email, { transactional: true })).toBe(true)
        })

        const HOUR = 60 * 60_000
        const DAY = 24 * HOUR
        // Steps run in processing order. Each age is how long ago SES saw the event, and no age means no SES timestamp.
        it.each([
            [
                'a delivery newer than the bounce',
                [
                    ['bounce', 2 * HOUR],
                    ['delivery', HOUR],
                ],
                false,
            ],
            [
                'a bounce older than a delivery, processed after it',
                [
                    ['bounce', 3 * HOUR],
                    ['delivery', HOUR],
                    ['bounce', 2 * HOUR],
                ],
                false,
            ],
            [
                'a bounce newer than the delivery',
                [
                    ['bounce', 3 * HOUR],
                    ['delivery', HOUR],
                    ['bounce', HOUR / 2],
                ],
                true,
            ],
            [
                'a bounce with no timestamp after a delivery',
                [['bounce', 3 * HOUR], ['delivery', HOUR], ['bounce']],
                true,
            ],
            [
                'a delivery at the same time as the bounce',
                [
                    ['bounce', HOUR],
                    ['delivery', HOUR],
                ],
                true,
            ],
            [
                'a bounce after a delivery that broke a long bounce run',
                [
                    ['bounce', 10 * DAY],
                    ['bounce', 9 * DAY],
                    ['delivery', 8 * DAY],
                    ['bounce', 2 * DAY],
                ],
                false,
            ],
        ] as [string, [('bounce' | 'delivery')?, number?][], boolean][])(
            'orders bounces and deliveries by when SES saw them: %s',
            async (label, steps, blocked) => {
                const email = `ordered-${label.replace(/\W+/g, '-')}-${team.id}@example.com`
                const svc = newService(true)
                const now = Date.now()
                for (const [kind, ago] of steps) {
                    const at = ago === undefined ? undefined : new Date(now - ago).toISOString()
                    if (kind === 'bounce') {
                        await svc.recordGlobalHardBounces([email], at)
                    } else {
                        await svc.recordDeliveries(team.id, [email], at, { clearGlobal: true })
                    }
                }

                expect(await newService(true).isSuppressed(team.id, email)).toBe(blocked)
            }
        )

        const lapseGlobalEntry = async (email: string): Promise<void> => {
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `UPDATE posthog_emailhardbounce
                 SET first_bounced_at = NOW() - INTERVAL '3 days', last_bounced_at = NOW() - INTERVAL '2 days'
                 WHERE email = $1`,
                [email],
                'test-lapse-global-hard-bounce'
            )
        }

        it.each([
            ['a delivery clears the global entry after no other event', 'delivery', false],
            ['a delivery clears the global entry after a delayed soft bounce for an earlier send', 'delivery', true],
            ['the global entry lapses', 'lapse', false],
        ] as const)("releases a team's copied block once %s", async (_label, clearedBy, softBounce) => {
            const email = `recovered-${clearedBy}-${softBounce ? 'soft' : 'plain'}-${team.id}@example.com`
            const otherTeamId = await bounceForAnotherTeam(email)
            expect(await newService(true).isSuppressed(team.id, email)).toBe(true)
            expect(await newService(true).isSuppressed(team.id, email)).toBe(true)
            if (softBounce) {
                await newService(true).recordTransientBounces(team.id, [email], 'smtp; 421 try again later')
            }

            if (clearedBy === 'lapse') {
                await lapseGlobalEntry(email)
            } else {
                await newService(true).recordDeliveries(
                    otherTeamId,
                    [email],
                    new Date(Date.now() + 60_000).toISOString(),
                    {
                        clearGlobal: true,
                    }
                )
            }

            expect(await newService(true).isSuppressed(team.id, email, { transactional: true })).toBe(false)
            expect(await readRow(email)).toMatchObject({ suppressed: false, deleted: false })
        })

        it("keeps the team's own hard bounce once the global entry lapses", async () => {
            const email = `own-bounce-${team.id}@example.com`
            await bounceForAnotherTeam(email)
            await newService(true).recordHardBounces(team.id, [email], 'smtp; 550 5.1.1 user unknown')
            await lapseGlobalEntry(email)

            expect(await newService(true).isSuppressed(team.id, email, { transactional: true })).toBe(true)
            expect(await readRow(email)).toMatchObject({ suppressed: true, deleted: false })
        })

        it('does not undo a removal that a lagging read missed', async () => {
            const email = `removed-${team.id}@example.com`
            await bounceForAnotherTeam(email)
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagesuppression
                    (id, team_id, identifier, source, reason, transient_bounce_count,
                     suppressed, suppressed_at, deleted, created_at, updated_at)
                 VALUES (gen_random_uuid(), $1, $2, 'BOUNCE', NULL, 0, false, NULL, true, NOW(), NOW())`,
                [team.id, email],
                'test-insert-removed-suppression'
            )

            await (newService(true) as any).upsertHardBounces(team.id, [email], 'copied', { keepRemoved: true })

            expect(await readRow(email)).toMatchObject({ suppressed: false, deleted: true })
        })
    })

    describe('cache invalidation', () => {
        it("a write for one team does not evict another team's cached entries", async () => {
            // Guards against a regression from markForRefresh(touchedKeys) back to clear() — clear()
            // would drop every team's cache on any write, causing a thundering-herd read against
            // Postgres in busy multi-tenant pods.
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const otherTeamId = await createTeam(hub.postgres, team.organization_id)
            const otherEmail = 'keep-me-cached@example.com'
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagesuppression
                    (id, team_id, identifier, source, reason, transient_bounce_count,
                     suppressed, suppressed_at, deleted, created_at, updated_at)
                 VALUES (gen_random_uuid(), $1, $2, 'BOUNCE', 'test row', 5,
                     true, NOW(), false, NOW(), NOW())`,
                [otherTeamId, otherEmail],
                'test-insert-other-team'
            )

            // Warm both teams' caches.
            expect(await svc.isSuppressed(otherTeamId, otherEmail)).toBe(true)

            // Simulate a state change we should NOT observe via cache (would only be visible via a
            // full cache clear + refetch): delete the row directly.
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `DELETE FROM posthog_messagesuppression WHERE team_id = $1 AND identifier = $2`,
                [otherTeamId, otherEmail],
                'test-delete-other-team'
            )

            // Trigger a write to `team.id` — must not invalidate other-team entries.
            await svc.recordTransientBounces(team.id, ['unrelated@example.com'], 'temp')

            // Other team's entry is still served from cache (would be `false` if clear() ran).
            expect(await svc.isSuppressed(otherTeamId, otherEmail)).toBe(true)
        })
    })

    describe('isSuppressed', () => {
        it.each([
            ['a bounce blocks marketing email', 'BOUNCE', 'test row', false, true],
            ['a soft-bounce suppression lets transactional email through', 'BOUNCE', 'test row', true, false],
            [
                'a hard bounce from before hard_bounced_at blocks transactional email',
                'BOUNCE',
                'Auto-suppressed after a hard bounce',
                true,
                true,
            ],
            ['a manual entry blocks marketing email', 'MANUAL', 'test row', false, true],
            ['a manual entry lets transactional email through', 'MANUAL', 'test row', true, false],
            [
                'an imported Customer.io invalid address blocks transactional email',
                'BOUNCE',
                'Imported from Customer.io (invalid address)',
                true,
                true,
            ],
            ['a complaint blocks marketing email', 'COMPLAINT', 'test row', false, true],
            ['a complaint lets transactional email through', 'COMPLAINT', 'test row', true, false],
            ['an address that is not on the list is not blocked', null, null, false, false],
        ] as const)('%s', async (_label, source, reason, transactional, expected) => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'listed@example.com'
            if (source) {
                await hub.postgres.query(
                    PostgresUse.COMMON_WRITE,
                    `INSERT INTO posthog_messagesuppression
                        (id, team_id, identifier, source, reason, transient_bounce_count,
                         suppressed, suppressed_at, deleted, created_at, updated_at)
                     VALUES (gen_random_uuid(), $1, $2, $3, $4, 0,
                         true, NOW(), false, NOW(), NOW())`,
                    [team.id, email, source, reason],
                    'test-insert-suppression'
                )
            }

            expect(await svc.isSuppressed(team.id, email, { transactional })).toBe(expected)
        })

        // A load that throws holds every send in the batch, so a bad key must not break a valid team's lookup.
        it.each<[string, unknown, string]>([
            ...INVALID_TEAM_ID_KEYS.map((key): [string, unknown, string] => [
                `invalid team id ${String(key)}`,
                key,
                'listed@example.com',
            ]),
            ['an address with a NUL byte', null, 'a\u0000b@example.com'],
        ])('keeps an address suppressed when %s shares its load', async (_case, badTeamId, badEmail) => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            const email = 'listed@example.com'
            await hub.postgres.query(
                PostgresUse.COMMON_WRITE,
                `INSERT INTO posthog_messagesuppression
                    (id, team_id, identifier, source, reason, transient_bounce_count,
                     suppressed, suppressed_at, deleted, created_at, updated_at)
                 VALUES (gen_random_uuid(), $1, $2, 'BOUNCE', 'test row', 5,
                     true, NOW(), false, NOW(), NOW())`,
                [team.id, email],
                'test-insert-suppression'
            )

            const results = await Promise.all([
                svc.isSuppressed(team.id, email),
                svc.isSuppressed((badTeamId ?? team.id) as number, badEmail),
            ])

            expect(results).toEqual([true, false])
        })
    })

    describe('write failures', () => {
        type WriteCall = (svc: EmailSuppressionService, throwOnFailure?: boolean) => Promise<void>
        const writes: [string, WriteCall][] = [
            [
                'recordTransientBounces',
                (svc, t) =>
                    svc.recordTransientBounces(team.id, ['a@example.com'], undefined, undefined, { throwOnFailure: t }),
            ],
            [
                'recordHardBounces',
                (svc, t) => svc.recordHardBounces(team.id, ['a@example.com'], undefined, { throwOnFailure: t }),
            ],
            [
                'recordGlobalHardBounces',
                (svc, t) => svc.recordGlobalHardBounces(['a@example.com'], undefined, { throwOnFailure: t }),
            ],
            [
                'recordComplaints',
                (svc, t) => svc.recordComplaints(team.id, ['a@example.com'], undefined, { throwOnFailure: t }),
            ],
            [
                'recordDeliveries',
                (svc, t) =>
                    svc.recordDeliveries(team.id, ['a@example.com'], '2024-01-01T00:00:00Z', { throwOnFailure: t }),
            ],
            [
                'recordDeliveries clearing the global list',
                (svc, t) =>
                    svc.recordDeliveries(team.id, ['a@example.com'], '2024-01-01T00:00:00Z', {
                        clearGlobal: true,
                        throwOnFailure: t,
                    }),
            ],
        ]

        it.each(writes)('%s rejects on a failed write only when asked to', async (_name, write) => {
            const svc = new EmailSuppressionService(hub.postgres, emailSuppressionConfigFromEnv())
            await hub.postgres.end()

            await expect(write(svc)).resolves.toBeUndefined()
            await expect(write(svc, true)).rejects.toThrow()
        })

        it('recordDeliveries rejects when only the global clear fails, when asked to', async () => {
            const email = `held-global-${team.id}@example.com`
            const config = emailSuppressionConfigFromEnv()
            await new EmailSuppressionService(hub.postgres, config).recordGlobalHardBounces(
                [email],
                new Date(Date.now() - 120_000).toISOString()
            )
            const impatientUrl = new URL(hub.DATABASE_URL)
            impatientUrl.searchParams.set('options', '-c lock_timeout=100')
            const impatient = new PostgresRouter({
                DATABASE_URL: impatientUrl.toString(),
                POSTGRES_CONNECTION_POOL_SIZE: 1,
            })
            const holder = new Client({ connectionString: hub.DATABASE_URL })
            await holder.connect()
            try {
                await holder.query('BEGIN')
                await holder.query('SELECT email FROM posthog_emailhardbounce WHERE email = $1 FOR UPDATE', [email])

                await expect(
                    new EmailSuppressionService(impatient, config).recordDeliveries(
                        team.id,
                        [email],
                        new Date().toISOString(),
                        { clearGlobal: true, throwOnFailure: true }
                    )
                ).rejects.toThrow('lock timeout')
            } finally {
                await holder.end()
                await impatient.end()
            }
            const enforcing = new EmailSuppressionService(hub.postgres, { ...config, globalHardBounceEnforce: true })
            expect(await enforcing.isSuppressed(team.id, email)).toBe(true)
        })
    })
})
