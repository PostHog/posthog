# CI → Sandboxed eval porting status

Tracks which `ee/hogai/eval/ci/` evals have been ported to `ee/hogai/eval/sandboxed/`,
and which are inherently harness-specific (tied to Max / LangChain / `AssistantGraph`
internals) and therefore cannot be ported one-for-one to the sandboxed harness
(Claude Code SDK + PostHog MCP).

## Porting status

| CI file                                                 | Status     | Sandbox counterpart                   | Portable?                 | Notes                                                                                                       |
| ------------------------------------------------------- | ---------- | ------------------------------------- | ------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `eval_funnel.py`                                        | Ported     | `product_analytics/eval_funnel.py`    | Yes                       | Asserts on `AssistantFunnelsQuery` produced via MCP `query-funnel`                                          |
| `eval_retention.py`                                     | Ported     | `product_analytics/eval_retention.py` | Yes                       | Asserts on `AssistantRetentionQuery` via MCP `query-retention`                                              |
| `eval_trends.py`                                        | Ported     | `product_analytics/eval_trends.py`    | Yes                       | Asserts on `AssistantTrendsQuery` via MCP `query-trends`                                                    |
| `eval_insight_search.py`                                | Partial    | `retrieval/eval_insight_retrieval.py` | Yes                       | Only the find-by-name → ID subset ported. `InsightEvaluationAccuracy` fuzzy-search scoring not yet ported.  |
| `eval_sql.py`                                           | Not ported | —                                     | Yes                       | Test via MCP `execute-sql` / HogQL exec                                                                     |
| `eval_surveys.py`                                       | Ported     | `surveys/eval_surveys.py`             | Yes                       | Asserts on `survey-create` payload/result, created survey ID in final message, and empty-question rejection |
| `eval_survey_analysis.py`                               | Not ported | —                                     | Maybe                     | Only if survey analysis is exposed via MCP; otherwise harness-specific                                      |
| `max_tools/eval_create_experiment_tool.py`              | Not ported | —                                     | Yes                       | MCP `experiment-create` exists                                                                              |
| `max_tools/eval_create_feature_flag_tool.py`            | Not ported | —                                     | Yes                       | MCP `feature-flag-create` exists                                                                            |
| `max_tools/eval_experiment_summary.py`                  | Not ported | —                                     | Yes                       | Read-only experiment querying via MCP                                                                       |
| `max_tools/eval_subscription_tool.py`                   | Not ported | —                                     | Yes                       | `managing-subscriptions` skill exists                                                                       |
| `max_tools/eval_upsert_dashboard.py`                    | Not ported | —                                     | Yes                       | MCP dashboard tools exist                                                                                   |
| `eval_memory.py`                                        | Not ported | —                                     | **No — harness-specific** | Tests Max's `core_memory_append/replace` tool from the root node                                            |
| `eval_memory_onboarding.py`                             | Not ported | —                                     | **No — harness-specific** | Max's slash-command onboarding flow                                                                         |
| `eval_root.py`                                          | Not ported | —                                     | **No — harness-specific** | Tests LangGraph root-node routing decisions                                                                 |
| `eval_root_documentation.py`                            | Not ported | —                                     | **No — harness-specific** | Root-node routing for docs tool                                                                             |
| `eval_root_entity_search.py`                            | Not ported | —                                     | **No — harness-specific** | Root-node routing for entity search                                                                         |
| `eval_root_style.py`                                    | Not ported | —                                     | **No — harness-specific** | Max persona / tone                                                                                          |
| `eval_ui_context.py`                                    | Not ported | —                                     | **No — harness-specific** | Max UI-context injection at the root                                                                        |
| `eval_ticket_summary.py`                                | Not ported | —                                     | **No — harness-specific** | Max slash command using `MaxChatAnthropic` (LangChain-wrapped Anthropic)                                    |
| `max_tools/eval_revenue_analytics_filter_generation.py` | Not ported | —                                     | **No — harness-specific** | `RevenueAnalyticsFilterOptionsGraph` — purpose-built LangGraph for in-product filter UI; not an MCP tool    |
| `max_tools/eval_session_replay_filter_generation.py`    | Not ported | —                                     | **No — harness-specific** | `SessionReplayFilterOptionsGraph` — same pattern as revenue filters                                         |

## Sandbox-only evals (no CI counterpart)

- `ci/eval_basic.py` — smoke/placeholder (bugfix + MCP pageview count)
- `product_analytics/eval_schema_discovery.py` — schema discovery exercise

## Mental model for harness-specificity

- **Harness-specific** evals assert on _which subgraph node Max's LangGraph router picked_,
  on Max-only constructs (core memory, slash commands, UI context, persona), or on dedicated
  in-product LangGraphs (`*FilterOptionsGraph`). The sandboxed agent has no equivalent
  router or persona — Claude Code SDK just chooses tools — so these don't transfer.
- **Portable** evals assert on the _artifact produced_ (a query, an entity created,
  a value retrieved). The three product-analytics ports prove the pattern: assert
  on the `AssistantTrendsQuery` (etc.) the agent ran via the corresponding MCP tool,
  regardless of which harness drove the call.
