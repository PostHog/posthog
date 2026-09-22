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
