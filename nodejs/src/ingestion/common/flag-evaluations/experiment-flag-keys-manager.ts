import { PostgresRouter, PostgresUse } from '~/common/utils/db/postgres'
import { LazyLoader } from '~/common/utils/lazy-loader'

/**
 * Per-team cache of flag keys that have a live (non-deleted) experiment linked.
 * The routing fork that will consume this must never send an experiment's exposure
 * events to the flag_evaluations table, so it will consult these sets for every
 * candidate event. That fork does not exist yet; today the only caller is the
 * measurement step, which makes the same lookup and records the answer so the
 * cost and the answer distribution are known before any behavior depends on them.
 *
 * Refresh cadence matches TeamManager for teams that have experiments, so a new
 * experiment on such a team is seen within ~2 minutes. Teams with no experiments
 * are the large majority and rarely change, so their empty result is held five
 * times longer to keep refresh volume off the read replica. The cost falls on the
 * transition that matters most: a team's first experiment can take ~10 minutes to
 * appear. The `$feature_flag_has_experiment` client hint narrows that window where it
 * is present, but it does not close it: the property is client-supplied and only
 * reaches SDKs on the v2 flags shape (the legacy and decide shapes drop `metadata`,
 * see rust/feature-flags/src/api/types.rs), so absence means unknown rather than
 * no-experiment. Treat it as a positive-only veto, and revisit this TTL if the routing
 * fork needs a bound that holds for traffic without the hint.
 */
export class ExperimentFlagKeysManager {
    private loader: LazyLoader<Set<string>>

    constructor(private postgres: PostgresRouter) {
        this.loader = new LazyLoader({
            name: 'ExperimentFlagKeysManager',
            refreshAgeMs: 2 * 60 * 1000, // 2 minutes
            refreshNullAgeMs: 10 * 60 * 1000, // 10 minutes, see the staleness note above
            refreshJitterMs: 30 * 1000, // 30 seconds
            // Retry transient load failures (e.g. a Postgres pooler scale-down returning
            // ECONNREFUSED), matching the Kafka consumer's TeamManager. The loader runs
            // detached in the LazyLoader buffer, so an un-retried transient failure can
            // surface as an unhandled rejection and restart the worker.
            loaderRetry: { retryIntervalMs: 250, retryJitterMs: 250, maxElapsedMs: 5000 },
            loader: (teamIds: string[]) => this.fetchExperimentFlagKeys(teamIds),
        })
    }

    /**
     * Experiment-backed flag keys per team, keyed by stringified team id. Batched
     * so a caller checking many flags pays one cache round-trip rather than one
     * per flag. A team with no experiments maps to null.
     *
     * Throws on loader failure, so callers must catch and fail toward NOT routing.
     */
    public async getExperimentFlagKeys(teamIds: number[]): Promise<Record<string, Set<string> | null>> {
        return await this.loader.getMany(teamIds.map(String))
    }

    private async fetchExperimentFlagKeys(teamIds: string[]): Promise<Record<string, Set<string> | null>> {
        // Keep in lockstep with live_experiment_exists in
        // products/experiments/backend/models/experiment.py (mirrored in
        // rust/feature-flags/src/flags/feature_flag_list.rs).
        //
        // The ff.deleted = false clause is a deliberate departure: the Django
        // predicate filters on the experiment's deleted state alone, so it answers
        // true for an experiment on a deleted flag where this answers false. A
        // deleted flag is never served, so the two can only disagree about a flag
        // nothing asks about, and excluding it here matches the effective Rust
        // behavior (which also requires f.deleted = false to select the flag).
        //
        // Scoping follows the flag rather than the experiment, as it does in Rust
        // (f.team_id = t.id). Callers ask whether their own team's flag key has an
        // experiment, so an experiment pointing at another team's flag must not answer
        // for the experiment's team. Nothing can create that row today, but the answer
        // shouldn't rest on a serializer keeping the two teams aligned.
        const result = await this.postgres.query<{ team_id: number; key: string }>(
            PostgresUse.COMMON_READ,
            `SELECT ff.team_id, ff.key
             FROM posthog_experiment e
             JOIN posthog_featureflag ff ON ff.id = e.feature_flag_id
             WHERE e.deleted = false AND ff.deleted = false AND ff.team_id = ANY($1)`,
            [teamIds.map(Number)],
            'fetchExperimentFlagKeys'
        )

        // Teams with no rows are left out; LazyLoader caches an omitted key as null for
        // refreshNullAgeMs, which is the answer they want anyway.
        const response: Record<string, Set<string> | null> = {}
        for (const row of result.rows) {
            ;(response[String(row.team_id)] ??= new Set()).add(row.key)
        }
        return response
    }
}

/** Returns undefined when measurement is off, so the absent manager is the gate. */
export function createExperimentFlagKeysManager(
    postgres: PostgresRouter,
    config: { EXPERIMENT_FLAG_KEYS_MEASUREMENT_ENABLED: boolean }
): ExperimentFlagKeysManager | undefined {
    return config.EXPERIMENT_FLAG_KEYS_MEASUREMENT_ENABLED ? new ExperimentFlagKeysManager(postgres) : undefined
}
