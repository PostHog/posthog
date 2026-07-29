// Evaluation summary limits
// This should match EVALUATION_SUMMARY_MAX_RUNS in backend/summarization/constants.py
export const EVALUATION_SUMMARY_MAX_RUNS = 250

// Compared against the string 'true', not `= true` or `= 1`: HogQL types $ai_evaluation_result from
// each team's own property definition, so teams that haven't registered it as Boolean extract the
// JSON bool as the string 'true' (where a numeric literal throws), while Boolean-registered teams
// still compare correctly against the string form. Reading the property directly rather than via
// JSONExtractString keeps the lookup on the properties_group_ai column and its bloom filter index.
// Same reasoning as the predicates in posthog/temporal/ai_observability/eval_reports/output_types.py.
export const EVALUATION_PASSED_HOGQL = "properties.$ai_evaluation_result = 'true'"
