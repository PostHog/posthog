import { withPostgres } from '../environment/stack'

export type VacuumSample = {
    liveTuples: number
    deadTuples: number
    autovacuums: number
    vacuums: number
    lastAutovacuumAt: number | null
    vacuumingSince: number | null
    heapBytes: number
    toastBytes: number
    indexBytes: Record<string, number>
}

export type VacuumSettings = {
    settings: Record<string, string>
    storage: Record<string, string[] | null>
    workersVisible: boolean
}

export type VacuumRead = { at: number } & (VacuumSample | { error: string })

export type VacuumSettingsRead = VacuumSettings | { error: string }

export interface VacuumProbe {
    sample(): Promise<VacuumSample>
    settings(): Promise<VacuumSettings>
}

type SampleRow = Record<Exclude<keyof VacuumSample, 'indexBytes'>, string | null> & {
    indexBytes: Record<string, number>
}

const epochMs = (value: string | null): number | null => (value === null ? null : Number(value))

export function createVacuumProbe(cyclotronUrl: string): VacuumProbe {
    return {
        sample: () =>
            withPostgres(async (client) => {
                const { rows } = await client.query<SampleRow>(
                    `SELECT
                         s.n_live_tup AS "liveTuples",
                         s.n_dead_tup AS "deadTuples",
                         s.autovacuum_count AS autovacuums,
                         s.vacuum_count AS vacuums,
                         extract(epoch FROM s.last_autovacuum) * 1000 AS "lastAutovacuumAt",
                         (SELECT extract(epoch FROM min(a.query_start)) * 1000
                          FROM pg_stat_progress_vacuum p JOIN pg_stat_activity a ON a.pid = p.pid
                          WHERE p.datid = (SELECT oid FROM pg_database WHERE datname = current_database())
                            AND p.relid = s.relid AND a.backend_type = 'autovacuum worker') AS "vacuumingSince",
                         pg_relation_size(s.relid) AS "heapBytes",
                         coalesce(pg_total_relation_size(nullif(c.reltoastrelid, 0)), 0) AS "toastBytes",
                         (SELECT coalesce(json_object_agg(i.indexrelname, pg_relation_size(i.indexrelid)), '{}')
                          FROM pg_stat_user_indexes i WHERE i.relid = s.relid) AS "indexBytes"
                     FROM pg_stat_user_tables s JOIN pg_class c ON c.oid = s.relid
                     WHERE s.relid = 'cyclotron_jobs'::regclass`
                )
                const [row] = rows
                return {
                    liveTuples: Number(row.liveTuples),
                    deadTuples: Number(row.deadTuples),
                    autovacuums: Number(row.autovacuums),
                    vacuums: Number(row.vacuums),
                    lastAutovacuumAt: epochMs(row.lastAutovacuumAt),
                    vacuumingSince: epochMs(row.vacuumingSince),
                    heapBytes: Number(row.heapBytes),
                    toastBytes: Number(row.toastBytes),
                    indexBytes: row.indexBytes,
                }
            }, cyclotronUrl),
        settings: () =>
            withPostgres(async (client) => {
                const settings = await client.query<{ name: string; value: string }>(
                    `SELECT name, current_setting(name) AS value
                     FROM pg_settings
                     WHERE name LIKE 'autovacuum%' OR name LIKE 'vacuum%' OR name = 'maintenance_work_mem'`
                )
                const storage = await client.query<{ name: string; options: string[] | null }>(
                    `SELECT c.relname AS name, c.reloptions AS options
                     FROM pg_class c
                     WHERE c.oid = 'cyclotron_jobs'::regclass
                        OR c.oid IN (SELECT indexrelid FROM pg_index WHERE indrelid = 'cyclotron_jobs'::regclass)`
                )
                // Without pg_read_all_stats, PostgreSQL hides an autovacuum worker's relation and start, so
                // vacuumingSince stays null whether or not a worker runs.
                const visibility = await client.query<{ visible: boolean }>(
                    `SELECT pg_has_role('pg_read_all_stats', 'USAGE') AS visible`
                )
                return {
                    settings: Object.fromEntries(settings.rows.map(({ name, value }) => [name, value])),
                    storage: Object.fromEntries(storage.rows.map(({ name, options }) => [name, options])),
                    workersVisible: visibility.rows[0].visible,
                }
            }, cyclotronUrl),
    }
}
