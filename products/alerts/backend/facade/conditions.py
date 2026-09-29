"""Custom alert conditions, as a source adapter and a configuration writer see them.

A writer compiles a condition once with `compile_alert_condition` and stores the bytecode. A
source builds one `ConditionContext` per evaluated window with `build_condition_contexts` and
runs each through `run_alert_condition` under one `ConditionBudget` per batch.
"""

from products.alerts.backend.logic.hog_condition import (
    CONDITION_BATCH_BUDGET,
    CONDITION_MAX_SOURCE_BYTES,
    CONDITION_MEMORY_LIMIT,
    CONDITION_RUN_TIMEOUT,
    AlertConditionValidationError,
    ConditionBudget,
    ConditionContext,
    ConditionResult,
    ConditionVerdict,
    build_condition_contexts,
    compile_alert_condition,
    compile_condition_bytecode,
    evaluate_condition_windows,
    run_alert_condition,
)

__all__ = [
    "CONDITION_BATCH_BUDGET",
    "CONDITION_MAX_SOURCE_BYTES",
    "CONDITION_MEMORY_LIMIT",
    "CONDITION_RUN_TIMEOUT",
    "AlertConditionValidationError",
    "ConditionBudget",
    "ConditionContext",
    "ConditionResult",
    "ConditionVerdict",
    "build_condition_contexts",
    "compile_alert_condition",
    "compile_condition_bytecode",
    "evaluate_condition_windows",
    "run_alert_condition",
]
