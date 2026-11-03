import { ExperimentStatsMethod } from '~/types'

export type SequentialSelection = 'default' | 'enabled' | 'disabled'

type SequentialConfig =
    | { sequential_testing_enabled?: boolean; sequential_tuning_parameter?: number }
    | null
    | undefined

export const DEFAULT_SEQUENTIAL_TUNING_PARAMETER = 5000
// Largest tuning parameter the backend will actually use. Values above this are reverted to
// the default at evaluation time (see _validate_numeric_range in
// posthog/hogql_queries/experiments/utils.py), so cap the inputs here to avoid a silent revert.
export const MAX_SEQUENTIAL_TUNING_PARAMETER = 1_000_000_000

export function getSequentialSelection(frequentist: SequentialConfig): SequentialSelection {
    const explicit = frequentist?.sequential_testing_enabled
    if (explicit === undefined) {
        return 'default'
    }
    return explicit ? 'enabled' : 'disabled'
}

export function resolveSequentialEnabled(frequentist: SequentialConfig, teamDefaultEnabled: boolean): boolean {
    return frequentist?.sequential_testing_enabled === undefined
        ? teamDefaultEnabled
        : !!frequentist.sequential_testing_enabled
}

export function resolveSequentialTuningParameter(
    frequentist: SequentialConfig,
    teamDefaultTuningParameter: number | null | undefined,
    fallback: number = DEFAULT_SEQUENTIAL_TUNING_PARAMETER
): number {
    if (typeof frequentist?.sequential_tuning_parameter === 'number') {
        return frequentist.sequential_tuning_parameter
    }
    if (typeof teamDefaultTuningParameter === 'number') {
        return teamDefaultTuningParameter
    }
    return fallback
}

type StatsConfig = { method?: string; frequentist?: SequentialConfig } | null | undefined

const PERCENTILE_SEQUENTIAL_DISABLED_REASON = "Percentile metrics don't support sequential testing yet"
const PERCENTILE_METRIC_SEQUENTIAL_DISABLED_REASON = `${PERCENTILE_SEQUENTIAL_DISABLED_REASON}. Turn off sequential testing in this experiment's statistics settings first.`

/** Sequential testing applies only to frequentist experiments, and an unset choice follows the team default. */
export function experimentUsesSequentialTesting(statsConfig: StatsConfig, teamDefaultEnabled: boolean): boolean {
    return (
        statsConfig?.method === ExperimentStatsMethod.Frequentist &&
        resolveSequentialEnabled(statsConfig.frequentist, teamDefaultEnabled)
    )
}

/** Why a metric list that includes a percentile metric can't be saved on this experiment, if it can't. */
export function percentileMetricSequentialReason(
    includesPercentileMetric: boolean,
    statsConfig: StatsConfig,
    teamDefaultEnabled: boolean
): string | undefined {
    return includesPercentileMetric && experimentUsesSequentialTesting(statsConfig, teamDefaultEnabled)
        ? PERCENTILE_METRIC_SEQUENTIAL_DISABLED_REASON
        : undefined
}

export interface PercentileSequentialBlocks {
    /** Why the stats settings can't turn sequential testing on */
    enabling?: string
    /** Why the stats settings can't follow the team default */
    teamDefault?: string
    /** Why the stats settings can't be saved as they are */
    save?: string
}

export function percentileSequentialBlocks(
    hasPercentileMetric: boolean,
    statsConfig: StatsConfig,
    teamDefaultEnabled: boolean
): PercentileSequentialBlocks {
    if (!hasPercentileMetric) {
        return {}
    }
    return {
        enabling: PERCENTILE_SEQUENTIAL_DISABLED_REASON,
        teamDefault: teamDefaultEnabled ? PERCENTILE_SEQUENTIAL_DISABLED_REASON : undefined,
        save: experimentUsesSequentialTesting(statsConfig, teamDefaultEnabled)
            ? `${PERCENTILE_SEQUENTIAL_DISABLED_REASON}. Turn it off to save.`
            : undefined,
    }
}
