import { closeHub, createHub } from '~/common/utils/db/hub'
import { PostgresUse } from '~/common/utils/db/postgres'
import { getFirstTeam, resetTestDatabase } from '~/tests/helpers/sql'
import { Hub, Team } from '~/types'

import { EmailSuppressionService } from './email-suppression.service'

interface SuppressionRow {
    identifier: string
    source: string
    suppressed: boolean
    transient_bounce_count: number
    deleted: boolean
}

describe('EmailSuppressionService', () => {
    let hub: Hub
    let team: Team
    let originalWriteEnv: string | undefined
    let originalEnforceEnv: string | undefined
    let originalThresholdEnv: string | undefined

    beforeEach(async () => {
        await resetTestDatabase()
        hub = await createHub()
        team = await getFirstTeam(hub.postgres)
        originalWriteEnv = process.env.EMAIL_SUPPRESSION_WRITE_ENABLED
        originalEnforceEnv = process.env.EMAIL_SUPPRESSION_ENFORCE_ENABLED
        originalThresholdEnv = process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD
    })

    afterEach(async () => {
        if (originalWriteEnv === undefined) {
            delete process.env.EMAIL_SUPPRESSION_WRITE_ENABLED
        } else {
            process.env.EMAIL_SUPPRESSION_WRITE_ENABLED = originalWriteEnv
        }
        if (originalEnforceEnv === undefined) {
            delete process.env.EMAIL_SUPPRESSION_ENFORCE_ENABLED
        } else {
            process.env.EMAIL_SUPPRESSION_ENFORCE_ENABLED = originalEnforceEnv
        }
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
            `SELECT identifier, source, suppressed, transient_bounce_count, deleted
             FROM posthog_messagesuppression
             WHERE team_id = $1 AND identifier = $2`,
            [team.id, email],
            'test-read-suppression'
        )
        return res.rows[0]
    }

    describe('recordTransientBounces (write flag on, threshold=3)', () => {
        beforeEach(() => {
            process.env.EMAIL_SUPPRESSION_WRITE_ENABLED = 'true'
            // Threshold=3 gives a clean boundary: 2 bounces must not flip, 3 must.
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '3'
        })

        it.each([
            ['below threshold — 2 consecutive bounces stay unsuppressed', 2, false],
            ['at threshold — the 3rd consecutive bounce flips suppressed', 3, true],
        ] as const)('%s', async (_label, bounces, expectedSuppressed) => {
            const svc = new EmailSuppressionService(hub.postgres)
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

    describe('recordDeliveries (write flag on)', () => {
        beforeEach(() => {
            process.env.EMAIL_SUPPRESSION_WRITE_ENABLED = 'true'
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '5'
        })

        it('resets the counter after a successful delivery so a transient outage does not accumulate', async () => {
            const svc = new EmailSuppressionService(hub.postgres)
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
            const svc = new EmailSuppressionService(hub.postgres)
            const email = 'no-timestamp@example.com'

            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect((await readRow(email))?.transient_bounce_count).toBe(1)

            await svc.recordDeliveries(team.id, [email])
            expect((await readRow(email))?.transient_bounce_count).toBe(1)
        })

        it('ignores a delivery older than the last bounce (out-of-order events)', async () => {
            // Guards against SES delivery + bounce notifications for different sends arriving in any
            // order — a late delivery for an older send must not erase a fresh bounce.
            const svc = new EmailSuppressionService(hub.postgres)
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
            const svc = new EmailSuppressionService(hub.postgres)
            const email = 'legit-recovering@example.com'

            await svc.recordTransientBounces(team.id, [email], 'temp')
            expect((await readRow(email))?.transient_bounce_count).toBe(1)

            const futureTimestamp = new Date(Date.now() + 60 * 60 * 1000).toISOString()
            await svc.recordDeliveries(team.id, [email], futureTimestamp)

            expect((await readRow(email))?.transient_bounce_count).toBe(0)
        })
    })

    describe('recordHardBounces (write flag on)', () => {
        beforeEach(() => {
            process.env.EMAIL_SUPPRESSION_WRITE_ENABLED = 'true'
            // Threshold irrelevant — hard bounces suppress on the first hit.
            process.env.EMAIL_SUPPRESSION_TRANSIENT_BOUNCE_THRESHOLD = '5'
        })

        it('suppresses immediately with source=BOUNCE and the diagnostic captured', async () => {
            const svc = new EmailSuppressionService(hub.postgres)
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
            const svc = new EmailSuppressionService(hub.postgres)
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

            const svc = new EmailSuppressionService(hub.postgres)
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

    describe('isSuppressed', () => {
        it('returns false when enforcement is disabled, even if a suppressed row exists (dark-launch gate)', async () => {
            // enforce env deliberately left unset — the gate must short-circuit before hitting the DB.
            const svc = new EmailSuppressionService(hub.postgres)
            const email = 'listed-but-not-enforced@example.com'
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

            expect(await svc.isSuppressed(team.id, email)).toBe(false)
        })

        describe('with enforcement enabled', () => {
            beforeEach(() => {
                process.env.EMAIL_SUPPRESSION_ENFORCE_ENABLED = 'true'
            })

            it.each([
                ['returns true for a suppressed row', true],
                ['returns false for an identifier that is not on the list', false],
            ])('%s', async (_label, expected) => {
                const svc = new EmailSuppressionService(hub.postgres)
                const email = expected ? 'listed@example.com' : 'not-listed@example.com'
                if (expected) {
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
                }

                expect(await svc.isSuppressed(team.id, email)).toBe(expected)
            })
        })
    })
})
