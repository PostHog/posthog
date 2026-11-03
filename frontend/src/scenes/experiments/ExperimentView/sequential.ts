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

export const PERCENTILE_SEQUENTIAL_DISABLED_REASON = "Percentile metrics don't support sequential testing yet"
export const PERCENTILE_METRIC_SEQUENTIAL_DISABLED_REASON = `${PERCENTILE_SEQUENTIAL_DISABLED_REASON}. Turn off sequential testing in this experiment's statistics settings first.`

/** Sequential testing applies only to frequentist experiments, and an unset choice follows the team default. */
export function experimentUsesSequentialTesting(
    statsConfig: { method?: string; frequentist?: SequentialConfig } | null | undefined,
    teamDefaultEnabled: boolean
): boolean {
    return (
        statsConfig?.method === ExperimentStatsMethod.Frequentist &&
        resolveSequentialEnabled(statsConfig.frequentist, teamDefaultEnabled)
    )
}
