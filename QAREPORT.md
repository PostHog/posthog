# 🔍 QA Team Review Report

| Key | Value |
| --- | --- |
| **Branch** | `posthog-code/show-dashboard-query-errors` |
| **Base** | `master` |
| **Files changed** | 5 |
| **Agents deployed** | 🧑‍💻 generalist-a, 🕵️ generalist-b, 🔒 security, ⚡ performance, 🎨 frontend, ✏️ copy |
| **Date** | 2026-07-28 |

---

## 📋 Summary

- Surfaces serialized insight query failures on dashboard tiles.
- Handles serialized failures during single-tile and full-dashboard refreshes.
- Adds initial-load and refresh error regression coverage.
- QA fixes ensure the newest refresh error wins and query IDs reach the error state.

### Key findings

- 🟡 Two reviewers independently found that a stale serialized error masked a newer refresh failure. Fixed.
- 🟢 Serialized query IDs were not forwarded to the displayed error state. Fixed.
- ✅ No security, performance, breakability, or copy issues found.

---

## 🏁 Verdict

> ✅ **APPROVE**

The convergent refresh-state issue and query ID omission are fixed. No open actionable findings remain.

---

## 👥 Agent summaries

| Agent | Risk | Summary |
| --- | --- | --- |
| 🧑‍💻 generalist-a | 🟡 MEDIUM | Found stale refresh-error precedence and missing query ID forwarding. |
| 🕵️ generalist-b | ⚪ NONE | Found no production-breaking behavior. |
| 🔒 security | ⚪ NONE | Found no auth, XSS, injection, or sensitive-data exposure issue. |
| ⚡ performance | ⚪ NONE | Work remains bounded by rendered tile count with no new requests or retained state. |
| 🎨 frontend | 🟡 MEDIUM | Independently found stale serialized errors masking newer refresh feedback. |
| ✏️ copy | ⚪ NONE | Error copy is clear and consistent with existing recovery actions. |

**Note:** ✏️ copy findings are always non-blocking nits. 🧑‍💻 generalist-a and 🕵️ generalist-b are independent generalist reviewers used for convergence validation.

---

## 📝 Findings

| # | Status | Priority | Finding | Location | Agents | Reasoning | Suggested fix |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ✅ Fixed | 🟡 Medium | New refresh error hidden by serialized error | `frontend/src/scenes/dashboard/DashboardItems.tsx:563` | generalist-a, frontend | The original `query_status` error always won, so later network or server failures displayed obsolete details. | Prefer the active refresh error and fall back to the serialized error. |
| 2 | ✅ Fixed | 🟢 Low | Query ID omitted from error state | `frontend/src/lib/components/Cards/InsightCard/InsightCard.tsx:377` | generalist-a | The helper retained the query ID in `ApiError.data`, but the error UI did not receive it for support and telemetry. | Forward `data.queryId` to `InsightErrorState`. |
