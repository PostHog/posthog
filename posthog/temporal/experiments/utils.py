from posthog.schema import ExperimentQueryResponse

# Default hour (UTC) for experiment recalculation when team has no specific time set
DEFAULT_EXPERIMENT_RECALCULATION_HOUR = 2  # 02:00 UTC


def remove_step_sessions_from_experiment_result(result: ExperimentQueryResponse) -> ExperimentQueryResponse:
    """
    Remove step_sessions values from experiment results to reduce API response size.
    """
    if result.baseline is not None:
        result.baseline.step_sessions = None

    if result.variant_results is not None:
        for variant in result.variant_results:
            variant.step_sessions = None

    return result
