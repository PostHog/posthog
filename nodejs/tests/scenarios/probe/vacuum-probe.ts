import { withPostgres } from '../environment/stack'

export type VacuumSample = {
    liveTuples: number
    deadTuples: number
    autovacuums: number
    vacuums: number
    lastAutovacuumAt: number | null
    vacuumingSince: number | null
    untrackedWorkers: number
    heapBytes: number
    toastBytes: number
    indexBytes: Record<string, number>
}

export type SettingType = { unit: string | null; vartype: string }

export type VacuumSettings = {
    settings: Record<string, string>
    types: Record<string, SettingType>
    storage: Record<string, string[] | null>
    statsHidden: boolean
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
                         (SELECT count(*) FROM pg_stat_activity a
                          WHERE a.datid = (SELECT oid FROM pg_database WHERE datname = current_database())
                            AND a.backend_type = 'autovacuum worker' AND a.state = 'disabled') AS "untrackedWorkers",
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
                    untrackedWorkers: Number(row.untrackedWorkers),
                    heapBytes: Number(row.heapBytes),
                    toastBytes: Number(row.toastBytes),
                    indexBytes: row.indexBytes,
                }
            }, cyclotronUrl),
        settings: () =>
            withPostgres(async (client) => {
                const settings = await client.query<{ name: string; value: string } & SettingType>(
                    `SELECT name, current_setting(name) AS value, unit, vartype
                     FROM pg_settings
                     WHERE name LIKE 'autovacuum%' OR name LIKE 'vacuum%' OR name = 'maintenance_work_mem'`
                )
                const storage = await client.query<{ name: string; options: string[] | null }>(
                    `SELECT c.relname AS name, c.reloptions AS options
                     FROM pg_class c
                     WHERE c.oid = 'cyclotron_jobs'::regclass
                        OR c.oid IN (SELECT indexrelid FROM pg_index WHERE indrelid = 'cyclotron_jobs'::regclass)`
                )
                const hidden = await client.query<{ hidden: boolean }>(
                    `SELECT EXISTS (
                         SELECT 1 FROM pg_stat_activity WHERE pid <> pg_backend_pid() AND backend_type IS NULL
                     ) AS hidden`
                )
                return {
                    settings: Object.fromEntries(settings.rows.map(({ name, value }) => [name, value])),
                    types: Object.fromEntries(
                        settings.rows.map(({ name, unit, vartype }) => [name, { unit, vartype }])
                    ),
                    storage: Object.fromEntries(storage.rows.map(({ name, options }) => [name, options])),
                    statsHidden: hidden.rows[0].hidden,
                }
            }, cyclotronUrl),
    }
}
