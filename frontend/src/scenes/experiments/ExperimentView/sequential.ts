export type SequentialSelection = 'default' | 'enabled' | 'disabled'

type SequentialConfig =
    | { sequential_testing_enabled?: boolean; sequential_tuning_parameter?: number }
    | null
    | undefined

export const DEFAULT_SEQUENTIAL_TUNING_PARAMETER = 5000

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
