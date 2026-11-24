"""The AI judge as the second member of an AND ensemble, for other products to reuse.

The caller runs the local members of the ensemble, and asks `judge_flagged_bucket` only about a bucket
they flag. Anomaly scoring uses it to confirm z-score flags.
"""

from products.alerts.backend.judge.contract import EarlierFlag, SeriesContext
from products.alerts.backend.judge.lazy_and import (
    MAX_JUDGE_CALL_SECONDS,
    JudgeMemberResult,
    LazyAndEnsemble,
    MemberState,
    NotEvaluatedReason,
    combined_flag,
    judge_flagged_bucket,
    not_evaluated,
    split_ai_member,
)

__all__ = [
    "MAX_JUDGE_CALL_SECONDS",
    "EarlierFlag",
    "JudgeMemberResult",
    "LazyAndEnsemble",
    "MemberState",
    "NotEvaluatedReason",
    "SeriesContext",
    "combined_flag",
    "judge_flagged_bucket",
    "not_evaluated",
    "split_ai_member",
]
