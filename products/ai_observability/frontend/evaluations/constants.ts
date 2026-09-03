// Most-recent runs fetched for an evaluation's runs table and its result badges
export const EVALUATION_RUNS_QUERY_LIMIT = 250

// Compared against the string 'true', not `= true` or `= 1`: HogQL types $ai_evaluation_result from
// each team's own property definition, so teams that haven't registered it as Boolean extract the
// JSON bool as the string 'true' (where a numeric literal throws), while Boolean-registered teams
// still compare correctly against the string form. Reading the property directly rather than via
// JSONExtractString keeps the lookup on the properties_group_ai column and its bloom filter index.
// Same reasoning as the predicates in posthog/temporal/ai_observability/eval_reports/output_types.py.
export const EVALUATION_PASSED_HOGQL = "properties.$ai_evaluation_result = 'true'"

// A skipped run was never graded, but an evaluation that disallows N/A still emits result=false
// alongside skipped=true, so any count that doesn't exclude skips reads them as failures. Mirrors
// _NOT_SKIPPED_PREDICATE in posthog/temporal/ai_observability/eval_reports/output_types.py, which
// the report metrics already apply — without this the two surfaces disagree about the same runs.
export const EVALUATION_NOT_SKIPPED_HOGQL =
    "(isNull(properties.$ai_evaluation_skipped) OR properties.$ai_evaluation_skipped != 'true')"
