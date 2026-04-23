# Fixtures for `investigating-billing-costs`

Sample MCP tool responses used by the skill's scripts for both testing and
documentation. Each fixture exercises one code path in the corresponding
script.

## Current contents

All files in this initial commit are **minimal synthetic fixtures**, trimmed to
the fields that `summarize_billing.py` reads. They are schema-accurate but not
reflective of any real customer. Replace with real captures as they become
available.

| File | Scenario | Used by |
| --- | --- | --- |
| `billing_list_paid_customer.json` | Paid plan, 3 active products, 1 addon, no near-limit products | `test_summarize_billing.py` |
| `billing_list_free_customer.json` | No active subscription, products present but unsubscribed | `test_summarize_billing.py` |
| `billing_list_near_limit.json` | Paid plan, one product at 85% of limit | `test_summarize_billing.py` |

## Capturing a real fixture

1. Run the tool against a local test customer, e.g.
   `mcp__posthog-local__billing-list`.
2. Claude Code stashes the response to
   `~/.claude/projects/<project>/tool-results/billing-list-<ts>.txt` when it
   exceeds the context budget. For small responses, copy from session JSONL
   instead.
3. Strip customer-identifying fields:
   - `stripe_customer_id`, `customer_id`
   - `account_owner.email`, `account_owner.name`
   - `stripe_portal_url`
   - Any `id`/`name` that would identify a real org
4. Save into this directory with a descriptive filename
   (`billing_list_<scenario>.json`) and update the table above.
5. Add or extend a test that exercises the new scenario.

## Why synthetic fixtures are acceptable as a starting point

The scripts they back are deterministic Python that reads specific fields.
The test contract is "given this shape in, produce that shape out". Synthetic
fixtures prove the shape contract; real fixtures prove that the shape
assumption matches production. Both are valuable; the synthetic ones unblock
shipping the script without waiting on a clean capture.
