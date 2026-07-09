---
name: investigating-alert-firings
description: >
  Investigate a firing PostHog insight alert end to end — read the trigger context,
  resolve the insight and dashboards, query the underlying events, and propose a
  mitigation with a structured report. Use when a task originates from an alert firing.
---

# Investigating alert firings

You were started because a PostHog insight alert transitioned into (or remains in) a firing state.
Your job: find out why, decide whether it warrants action, and propose a mitigation.

## Workflow

1. **Read the trigger context.**
   The task description carries the alert name, breach values (`calculated_value` vs threshold bounds or detector detail), the insight short id, dashboard deep links, and the `alert_check_id`.
   The breach values come from the insight's own configuration — dashboards apply their own filters, so dashboard-filtered numbers may legitimately differ.
2. **Honor the alert owner's instructions.**
   If the description has an "Alert owner's instructions" section, follow it.
   If it names a skill, read and prefer that skill over your own judgment.
3. **Read the team's investigation skills.**
   The description lists this team's `investigation-*` skills; fetch them with the PostHog skill MCP tools before querying.
4. **Resolve the insight.**
   Fetch the insight and its query; understand what the metric actually measures before touching events.
5. **Query the failure events.**
   Use the PostHog MCP query tools to break the metric down around the breach window: by time, by relevant properties, by version/deploy markers.
   Compare against the same window in previous periods.
6. **Classify.**
   `false_positive` means the breach is arithmetically real but expected or benign — seasonality, a known deploy, test traffic.
   `true_positive` means it warrants action.
   `inconclusive` when the data does not support either.
7. **Propose a mitigation.**
   Concrete and minimal.
   If a repository is configured and the cause is code-level, open a **draft** PR.
8. **On a re-run** (the description links a previous task run): build on the prior findings and **update the existing draft PR** instead of opening a new one.

## Report

Finish by setting your structured output: findings, suspected_cause, proposed_mitigation, confidence (0-1), verdict, and pr_url when you opened or updated a PR.
