# Depot Runner Communication Loss — Urgent Escalation

**Status:** ACTIVE — Chronic recurring issue since March 2025  
**Severity:** High — Blocks CI for all affected commits  
**Contact:** Depot support (urgent priority)

## Summary

Depot runners intermittently lose communication with GitHub Actions before any workflow steps execute. Jobs fail with 0-1 completed steps after a timeout of 300–1200 seconds. The issue has been recurring since March 2025 with escalating severity and frequency. No PostHog-side changes correlate with the failures — this is entirely a Depot infrastructure problem.

## Failure Signature

- **Symptom:** Jobs complete with 0 or 1 step (empty step name), conclusion = `failure`
- **Duration:** 300–1200 seconds (originally clustered ~600s, now spread across full range)
- **Error message (when logged):** `The self-hosted runner lost communication with the server.`
- **Runner labels:** `depot-ubuntu-latest-4` (primary), other Depot runners also affected
- **No workflow code executes** — failure occurs at runner registration/communication level

## Recurrence Timeline (Escalating Severity)

| Date                       | Zero-Step Failures      | Notes                                                |
| -------------------------- | ----------------------- | ---------------------------------------------------- |
| Mar 9, 2025                | First known             | Initial occurrence                                   |
| Mar 20                     | 6                       | Runner `depot-qnmzzzwdr7`, commit `b37ab5b50e`       |
| Mar 24–25                  | 30                      | Backend CI matrix jobs                               |
| Apr 6                      | 30                      | 5 commits, 7 runs in 27 minutes (20:40–21:07 UTC)    |
| Apr 7                      | 154                     | 20 commits, 45 runs, 9 workflows over 11+ hours      |
| Apr 11                     | 11                      |                                                      |
| Apr 13–17                  | 47–365/day              | Multi-day spike                                      |
| Apr 20–24                  | 152–413/day             | Sustained degradation                                |
| Apr 27–30                  | 489–994/day             | **Worst sustained period**                           |
| May 1–8                    | 3–745/day               | Continued instability                                |
| May 11–14                  | 39–176/day              |                                                      |
| May 18–22                  | 135–369/day             | Multi-day spike                                      |
| May 26                     | **1,097**               | Massive spike, 193+ unique failures in 20 min window |
| May 27–29                  | 113–328/day             | Post-spike continuation                              |
| May 31                     | 50                      |                                                      |
| **Jun 1 (today, partial)** | **180+ (by 14:00 UTC)** | Active and escalating                                |

### Cumulative Impact (Mar 20 – Jun 1)

- **Total zero-step failures:** ~11,000+ in the last 60 days alone
- **Peak single-day:** 1,097 failures (May 26)
- **Peak sustained period:** 994/day (Apr 28)
- **Days with >100 failures:** 30+ out of 73 days tracked
- **Affected workflows:** Node.js CI, Backend CI, Frontend CI, MCP CI, Container Images CD, Rust CI, Dagster CI

## Today's Failures (Jun 1, 2025) — Sample

| Time (UTC) | Workflow            | Job                     | Duration (s) | Commit     |
| ---------- | ------------------- | ----------------------- | ------------ | ---------- |
| 14:04      | Node.js CI          | Node.js Tests 1/3       | 1036         | `99b0537d` |
| 14:03      | Frontend CI         | Jest test (EE - 1)      | 688          | `2e57bf9f` |
| 13:47      | Backend CI          | Django tests – Temporal | 942          | `a20ccbc1` |
| 13:47      | Backend CI          | Django tests – Core     | 978          | `8fccf744` |
| 13:41      | Node.js CI          | Node.js Tests 3/3       | 1073         | `99b0537d` |
| 13:39      | Node.js CI          | Node.js Tests 2/3       | 780          | `fbba0413` |
| 13:38      | MCP CI              | Integration Tests       | 720          | `59c23f0e` |
| 13:38      | Container Images CD | Build and push PostHog  | 600          | `1e3378bd` |
| 12:51      | Node.js CI          | Node.js Tests 3/3       | 914          | `989bc9e7` |
| 10:44      | Node.js CI          | Node.js Tests 3/3       | 935          | `2834722b` |

## Impact on PostHog CI

1. **Blocks master:** Gate jobs (Django Tests Pass, Rust Tests Pass, etc.) fail because they treat failed matrix jobs as failures
2. **Forces retries:** Every zero-step failure requires a manual re-run
3. **Wastes compute:** 300–1200s of billed runner time per failure with zero useful work
4. **Erodes confidence:** Engineers cannot distinguish Depot failures from real test failures without manual inspection
5. **Cumulative cost:** At 180 failures/day × ~700s average = 35+ hours of wasted runner time daily

## What We Need From Depot

1. **Immediate acknowledgment** of ongoing degradation (Jun 1 is actively escalating)
2. **Root cause analysis** — What infrastructure events correlate with these failure windows?
3. **Timeline of changes** — What has Depot changed in runner provisioning/networking since March?
4. **Prevention plan** — What specific changes will Depot implement to prevent recurrence?
5. **SLA commitment** — What runner availability SLA can Depot commit to?
6. **Monitoring/alerting** — Does Depot have visibility into these failures on their side? If not, why not?
7. **Interim mitigation** — Can Depot implement automatic runner health checks or faster failover?

## Key Runner IDs for Investigation

- `depot-qnmzzzwdr7` (Mar 20 episode)
- Runner label: `depot-ubuntu-latest-4` (primary affected label across all episodes)

## Reproduction Query

To verify current failure rate, query GitHub Actions jobs for PostHog/posthog where:

- `job_conclusion = 'failure'`
- `length(step_names) <= 1` (no steps executed)
- `duration_millis BETWEEN 300000 AND 1200000`

## Previous Communications

This issue was first reported in March 2025. It has never been permanently resolved — only oscillates between low-level background failures and acute spikes. The current escalation is necessary because:

- The issue has persisted for **73+ days** without permanent fix
- Severity is **increasing** (peak days getting worse: 154 → 994 → 1,097)
- Impact is **broadening** (more workflows, wider duration range)
- There is no sign of stabilization

---

_Document prepared: June 1, 2025_  
_Data source: GitHub Actions CI logs for PostHog/posthog_
