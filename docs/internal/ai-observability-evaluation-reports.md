# Evaluation report count triggers

An evaluation report configured for "Every N evaluations" counts matching results since its last delivery.
For a report that has not been delivered, the count starts at its configured start time or creation time.
Results remain eligible until a report is delivered, even when reaching the threshold takes more than seven days.
For example, a report with a threshold of 100 and 10 new results per day becomes due after ten days.
Cooldowns and daily delivery limits still apply.

## Query time limits

The coordinator checks count-triggered reports every five minutes and groups queries by team.
Each report retains its own start time within the shared query.
If a query times out, the check divides its time range and adds the counts from the two non-overlapping ranges.
The check requests an error on timeout so partial counts cannot be mistaken for complete results.

Queries and their split retries share a 100-second execution budget within a 120-second activity timeout.
The initial query keeps its 30-second limit; split retries request at most 15 seconds each.
Each attempt reserves room for a twofold overrun and reduces its limit when the remaining budget requires it.
If the remaining budget cannot support another attempt, the activity fails and follows its retry policy.
The execution budget limits query work; it does not discard older results or guarantee that every report can be checked within that budget.

### Numeric evaluation eligibility

Numeric evaluations need a passing rule to generate reports.
Adding the first passing rule creates its default report if none exists, including while the evaluation is paused.
Delivery waits until the evaluation is enabled.
Renaming, pausing, or deleting an evaluation does not create a report.
If an evaluation loses report support before report generation starts, generation stops without an error or a delivery.

Reports classify scores using the rule captured at the start of generation.
Saving a changed passing rule updates live views of historical scores, while previously generated reports keep their saved metrics.
Unsaved rules apply only to test previews; the runs table and summary use the saved rule.
Pass rates are unavailable when no runs have been graded.

Scores outside the configured bounds produce a visible skipped run, for both Hog and LLM judge evaluations.
An invalid Hog return type, such as a boolean for a numeric evaluation, disables the evaluation until its code is fixed.
The optional numeric `step` guides scoring and does not round or reject results.
