# Table for storing lazy-precomputed web goals (conversion) aggregates.
#
# One row per (team, job, UTC hour, action_id) where action_id is one of the
# top-5 actions the runner picks at query time
# (`Action.objects…order_by("pinned_at", "-last_calculated_at")[:5]`). The set
# of action expressions and IDs is baked into the INSERT AST and therefore the
# lazy_computation cache key — a different top-5 set yields a different job_id,
# so storing only the integer `action_id` is enough; the action expression
# itself doesn't need to live in the row.
#
# At read time the response is pivoted back to the runner's column layout
# (current/previous count + uniq person tuples per action) using
# `sumStateIf` / `uniqStateIf` keyed by `action_id`.


TABLE_BASE_NAME = "web_goals_preaggregated"


def DISTRIBUTED_WEB_GOALS_PREAGGREGATED_TABLE():
    return TABLE_BASE_NAME
