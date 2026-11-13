import { randomBytes, randomUUID } from 'crypto'
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'fs'
import path from 'path'

import { CyclotronV2Manager } from '~/cdp/services/cyclotron-v2/manager'
import { CyclotronV2JobInit } from '~/cdp/services/cyclotron-v2/types'
import { parseJSON } from '~/common/utils/json-parse'

import type { Backlog, Profile } from '../cards'
import { durationMs } from '../duration'
import { RESIDENT_TEAMS_FROM, withPostgres } from '../environment/stack'

export type ResidentRows = { teamId: number; status: string; rows: number }

export type Footprint = { table: number; indexes: number; toast: number }

export type BacklogManifest = {
    profile: string
    backlog: Backlog
    seededAt: string
    rows: ResidentRows[]
    bytes: Footprint
}

export type QueueCount = { queue: string; target: number; live: number; withinTolerance: boolean }

export type SeedResult = { queues: QueueCount[]; bytes: Footprint; manifest?: string }

export type ResidentBacklog = {
    profile: Pick<Profile, 'name' | 'backlog'>
    seeded?: Pick<BacklogManifest, 'profile' | 'backlog' | 'rows'>
    found: ResidentRows[]
}

const BATCH_JOBS = 500
const BATCH_BYTES = 8 * 1024 * 1024

export const manifestPathOf = (stateDir: string): string => path.join(stateDir, 'backlog.json')

function stateSizeAt(i: number, count: number, { p50, p90, p99 }: Backlog['stateBytes']): number {
    const anchors: [number, number][] = [
        [0, p50 / 2],
        [0.5, p50],
        [0.9, p90],
        [0.99, p99],
        [1, p99],
    ]
    const q = (i + 0.5) / count
    const upper = anchors.findIndex(([at]) => at >= q)
    const [q0, s0] = anchors[upper - 1]
    const [q1, s1] = anchors[upper]
    return Math.max(1, Math.round(s0 + ((s1 - s0) * (q - q0)) / (q1 - q0)))
}

function residentState(size: number, compressibility: number): Buffer {
    const random = Math.round(size * (1 - compressibility))
    return Buffer.concat([randomBytes(random), Buffer.alloc(size - random, 'a')])
}

function* residentJobs(backlog: Backlog, scheduled: Date): Generator<CyclotronV2JobInit> {
    const functions = Array.from({ length: backlog.teams }, () => randomUUID())
    for (const [queueName, count] of Object.entries(backlog.jobs)) {
        for (let i = 0; i < count; i++) {
            yield {
                teamId: RESIDENT_TEAMS_FROM + (i % backlog.teams),
                functionId: functions[i % backlog.teams],
                queueName,
                scheduled,
                state: residentState(stateSizeAt(i, count, backlog.stateBytes), backlog.compressibility),
            }
        }
    }
}

function* batchesOf(jobs: Iterable<CyclotronV2JobInit>): Generator<CyclotronV2JobInit[]> {
    let batch: CyclotronV2JobInit[] = []
    let bytes = 0
    for (const job of jobs) {
        batch.push(job)
        bytes += job.state?.length ?? 0
        if (batch.length >= BATCH_JOBS || bytes >= BATCH_BYTES) {
            yield batch
            batch = []
            bytes = 0
        }
    }
    if (batch.length > 0) {
        yield batch
    }
}

export async function residentRows(cyclotronUrl: string): Promise<ResidentRows[]> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<ResidentRows>(
            `SELECT team_id AS "teamId", status::text AS status, count(*)::int AS rows
             FROM cyclotron_jobs WHERE team_id >= $1 GROUP BY 1, 2 ORDER BY 1, 2`,
            [RESIDENT_TEAMS_FROM]
        )
        return rows
    }, cyclotronUrl)
}

async function liveRowsPerQueue(cyclotronUrl: string): Promise<Map<string, number>> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<{ queue: string; live: number }>(
            `SELECT queue_name AS queue, count(*)::int AS live
             FROM cyclotron_jobs WHERE team_id >= $1 AND status = 'available' AND scheduled > now() GROUP BY 1`,
            [RESIDENT_TEAMS_FROM]
        )
        return new Map(rows.map(({ queue, live }) => [queue, live]))
    }, cyclotronUrl)
}

async function footprintOf(cyclotronUrl: string): Promise<Footprint> {
    return await withPostgres(async (client) => {
        const { rows } = await client.query<Record<keyof Footprint, string>>(
            `SELECT pg_relation_size(oid) AS table,
                    pg_indexes_size(oid) AS indexes,
                    COALESCE(pg_total_relation_size(NULLIF(reltoastrelid, 0)), 0) AS toast
             FROM pg_class WHERE oid = 'cyclotron_jobs'::regclass`
        )
        const [{ table, indexes, toast }] = rows
        return { table: Number(table), indexes: Number(indexes), toast: Number(toast) }
    }, cyclotronUrl)
}

export async function seedBacklog(
    profile: string,
    backlog: Backlog,
    cyclotronUrl: string,
    stateDir: string
): Promise<SeedResult> {
    const now = new Date()
    const manifest = manifestPathOf(stateDir)
    rmSync(manifest, { force: true })
    await withPostgres(
        (client) => client.query('DELETE FROM cyclotron_jobs WHERE team_id >= $1', [RESIDENT_TEAMS_FROM]),
        cyclotronUrl
    )
    const manager = new CyclotronV2Manager({ pool: { dbUrl: cyclotronUrl, maxConnections: 1 } })
    await manager.connect()
    try {
        const scheduled = new Date(now.getTime() + durationMs(backlog.parkFor))
        for (const batch of batchesOf(residentJobs(backlog, scheduled))) {
            await manager.bulkCreateJobs(batch)
        }
    } finally {
        await manager.disconnect()
    }

    const live = await liveRowsPerQueue(cyclotronUrl)
    const queues = Object.entries(backlog.jobs).map(([queue, target]) => {
        const rows = live.get(queue) ?? 0
        return { queue, target, live: rows, withinTolerance: Math.abs(rows - target) <= backlog.tolerance * target }
    })
    const bytes = await footprintOf(cyclotronUrl)
    if (queues.some(({ withinTolerance }) => !withinTolerance)) {
        return { queues, bytes }
    }
    const written: BacklogManifest = {
        profile,
        backlog,
        seededAt: now.toISOString(),
        rows: await residentRows(cyclotronUrl),
        bytes,
    }
    mkdirSync(stateDir, { recursive: true })
    writeFileSync(manifest, JSON.stringify(written, null, 2))
    return { queues, bytes, manifest }
}

export function readManifest(stateDir: string): BacklogManifest | undefined {
    const manifest = manifestPathOf(stateDir)
    return existsSync(manifest) ? (parseJSON(readFileSync(manifest, 'utf8')) as BacklogManifest) : undefined
}

export async function residentBacklogOf(
    profile: Pick<Profile, 'name' | 'backlog'>,
    stateDir: string,
    cyclotronUrl: string
): Promise<ResidentBacklog> {
    const manifest = readManifest(stateDir)
    return {
        profile,
        seeded: manifest && { profile: manifest.profile, backlog: manifest.backlog, rows: manifest.rows },
        found: await residentRows(cyclotronUrl),
    }
}
