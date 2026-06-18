import { Pool, PoolClient } from 'pg'

import { EMAIL_DEQUEUE_BLOCK_SIZE } from './manager'

/**
 * Rows scheduled more than this far in the future skip `dequeue_seq` assignment
 * at insert time. The janitor's `promoteScheduledEmailJobs` pass (and the email
 * consumer's fallback interval) assign the seq when the row's `scheduled` enters
 * the window. Picked to comfortably exceed the janitor's `cleanupIntervalMs`
 * (default 10s) so a ready-now row always gets its seq at insert, never via
 * promotion.
 *
 * Future rows kept out of the partial index `idx_cyclotron_jobs_email_fair_dequeue`
 * (whose predicate now includes `AND dequeue_seq IS NOT NULL`), so the
 * dequeue scan doesn't have to walk past them. Without this, a tenant
 * staging a large onboarding batch would pin the fair dequeue for every
 * subsequent ready row from any other tenant whose seq sorts after the
 * batch's block — see `worker.ts fairDequeueJobs` doc.
 */
export const EMAIL_DEQUEUE_ASSIGNMENT_WINDOW_MS = 30_000

/**
 * Bump per-team email counters atomically in one UPSERT and return the new
 * per-team counter values (the team's high watermark after the bump). Shared
 * by `manager.ts computeEmailDequeueSeqs` (insert path, autocommit on a
 * Pool) and `promoteScheduledEmailJobs` (transactional, on a PoolClient that
 * also holds the SELECT FOR UPDATE SKIP LOCKED across the multi-stage pass).
 *
 * Hatchet `p_max_assigned`: new-team rows insert at `MAX(counter) + increment`
 * so a brand-new tenant can't slot ahead of established tenants by starting
 * at counter=1. Existing-team rows add just `increment` (we subtract the MAX
 * shift back out in the ON CONFLICT branch). MAX is computed once via the CTE.
 */
export async function bumpTeamCounters(
    poolOrClient: Pool | PoolClient,
    teamIds: number[],
    increments: number[]
): Promise<Map<number, bigint>> {
    const result = await poolOrClient.query<{ team_id: number; counter: string }>(
        `WITH max_counter AS (
             SELECT COALESCE(MAX(counter), 0) AS m FROM cyclotron_email_team_seq
         )
         INSERT INTO cyclotron_email_team_seq (team_id, counter)
         SELECT team_id, increment + (SELECT m FROM max_counter)
         FROM unnest($1::int[], $2::bigint[]) AS t(team_id, increment)
         ON CONFLICT (team_id) DO UPDATE
            SET counter = cyclotron_email_team_seq.counter
                        + (EXCLUDED.counter - (SELECT m FROM max_counter))
         RETURNING team_id, counter`,
        [teamIds, increments]
    )
    return new Map(result.rows.map((r) => [r.team_id, BigInt(r.counter)]))
}

/**
 * Promote email-queue rows from `dequeue_seq IS NULL` to a fresh per-team seq
 * so they enter the fair-dequeue partial index and become dequeueable.
 * Two kinds of NULL rows match:
 *   1. Future-scheduled rows that have just entered the assignment window.
 *   2. Legacy rows from before the index-tightening migration.
 *
 * Wrapped in a single explicit transaction. Row-level locks acquired by
 * `FOR UPDATE SKIP LOCKED` in stage 1 are held until COMMIT, so a concurrent
 * promoter (janitor + email consumer fallback overlapping) sees the rows
 * we've claimed as locked and skips them. Without the transaction the locks
 * release between stages and both promoters would re-pick the same rows,
 * double-bumping the per-team counter and leaking counter range — not a
 * correctness bug (seqs stay unique because of `+ team_id`) but it inflates
 * the team's counter relative to the seqs actually written, unfairly
 * demoting busier teams over time.
 *
 * Returns the number of rows promoted.
 */
export async function promoteScheduledEmailJobs(pool: Pool, batchSize: number): Promise<number> {
    const client = await pool.connect()
    try {
        await client.query('BEGIN')

        // Stage 1: pick + lock candidates. Locks held until COMMIT below.
        const candidates = await client.query<{ id: string; team_id: number }>(
            `SELECT id, team_id
             FROM cyclotron_jobs
             WHERE queue_name = 'email'
               AND status = 'available'
               AND dequeue_seq IS NULL
               AND scheduled <= NOW() + make_interval(secs => $1::float)
             ORDER BY scheduled ASC
             LIMIT $2
             FOR UPDATE SKIP LOCKED`,
            [EMAIL_DEQUEUE_ASSIGNMENT_WINDOW_MS / 1000, batchSize]
        )

        if (candidates.rows.length === 0) {
            await client.query('COMMIT')
            return 0
        }

        // Group candidates by team so each team's counter bumps once.
        const indicesByTeam = new Map<number, number[]>()
        for (let i = 0; i < candidates.rows.length; i++) {
            const teamId = candidates.rows[i].team_id
            const existing = indicesByTeam.get(teamId)
            if (existing) {
                existing.push(i)
            } else {
                indicesByTeam.set(teamId, [i])
            }
        }
        const teamIds = [...indicesByTeam.keys()]
        const increments = teamIds.map((id) => indicesByTeam.get(id)!.length)

        // Stage 2: bump per-team counters on the same client so the bump
        // participates in this transaction.
        const newCounters = await bumpTeamCounters(client, teamIds, increments)

        // Stage 3: derive per-row seqs and apply a batched UPDATE.
        const ids: string[] = new Array(candidates.rows.length)
        const seqs: string[] = new Array(candidates.rows.length)
        for (const [teamId, indices] of indicesByTeam) {
            const newCounter = newCounters.get(teamId)
            if (newCounter === undefined) {
                continue
            }
            const startCounter = newCounter - BigInt(indices.length) + 1n
            const teamIdBigInt = BigInt(teamId)
            for (let k = 0; k < indices.length; k++) {
                const counterForThisJob = startCounter + BigInt(k)
                ids[indices[k]] = candidates.rows[indices[k]].id
                // pg accepts BIGINT as string to avoid JS number precision loss
                seqs[indices[k]] = (counterForThisJob * EMAIL_DEQUEUE_BLOCK_SIZE + teamIdBigInt).toString()
            }
        }

        await client.query(
            `UPDATE cyclotron_jobs cj
             SET dequeue_seq = u.seq::bigint
             FROM unnest($1::uuid[], $2::bigint[]) AS u(id, seq)
             WHERE cj.id = u.id`,
            [ids, seqs]
        )

        await client.query('COMMIT')
        return candidates.rows.length
    } catch (err) {
        // Best-effort rollback — if the connection itself is gone the
        // ROLLBACK will throw; we don't want that to mask the real error.
        await client.query('ROLLBACK').catch(() => {})
        throw err
    } finally {
        client.release()
    }
}

/**
 * Number of email rows whose `scheduled` time has passed but which still
 * have `dequeue_seq IS NULL` — i.e. they should be dequeueable but aren't
 * yet because nothing has promoted them. Powers the
 * `cdp_cyclotron_v2_promotion_lag` gauge.
 *
 * In healthy steady state this should hover near 0 — rows enter this count
 * briefly when their `scheduled` arrives, then leave on the next janitor
 * tick. Sustained non-zero = janitor down or promotion broken. Page on it.
 */
export async function countPromotionLag(pool: Pool): Promise<number> {
    const result = await pool.query<{ n: string }>(
        `SELECT COUNT(*)::bigint AS n
         FROM cyclotron_jobs
         WHERE queue_name = 'email'
           AND status = 'available'
           AND dequeue_seq IS NULL
           AND scheduled <= NOW()`
    )
    return parseInt(result.rows[0].n, 10)
}
