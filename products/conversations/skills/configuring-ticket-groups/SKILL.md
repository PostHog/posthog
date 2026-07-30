---
name: configuring-ticket-groups
description: >
  Configure a team's ticket groups — the ordered, filter-based priority groups the support
  tickets list ranks by. Use when the user wants to define, reorder, edit, or reset their
  ticket priority groups ("work Enterprise tickets before free-plan ones", "add a VIP tier",
  "put fresh email tickets first", "change our triage order"), or asks why tickets sort the
  way they do when the list is grouped.
---

# Configuring ticket groups

Ticket groups tell the Conversations tickets list which tickets to work first. A team defines an
ordered list of groups, each with a label and a set of filters. Sorting the list by ticket group
(`order_by=ticket_group` on `conversations-tickets-list`) orders tickets by group (top group
first), then by SLA deadline within each group (soonest first, no deadline last), and the response
carries a `ticket_group_counts` object with per-group totals. One click gives the team their
"work next" order.

## How ranking works

- Groups are stored per team in `conversations_settings.ticket_groups` as an ordered
  `[{label, filters[]}]` list. **List order is priority order** — the first group is worked first.
- Within a group, **ALL filters must match** (AND). Across groups, the **FIRST** matching group
  wins — groups may overlap, the earlier one takes the ticket.
- A group with an **empty** filters list matches nothing (a placeholder while configuring).
- Tickets matching **no** group rank with the **first** group. That's deliberate triage semantics:
  an unmatched ticket needs eyes, not burial. Advise users to keep a "Triage"-style group at the top.
- A team with no saved groups follows a small built-in example (Triage / Urgent / VIP, matched by
  the `needs_triage` / `urgent` / `vip` tags).

## The filter vocabulary

Each filter is one of:

- `{"type": "ticket_tags", "operator": "any_of", "value": ["vip", ...]}` — the ticket has ANY of
  these tags. Matching is exact: `urgent_billing` does not match `urgent`.
- `{"type": "ticket_property", "key": "channel_source" | "status" | "priority", "operator": "in",
"value": [...]}` — channel_source: widget/email/slack/teams/github; status: new/open/pending/on_hold/resolved;
  priority: low/medium/high/critical.
- `{"type": "ticket_property", "key": "email_from", "operator": "icontains", "value": "@bigcorp.com"}`
  — case-insensitive substring of the sender.
- `{"type": "ticket_property", "key": "sla_due_at", "operator": "is_set" | "is_not_set"}` — no
  `value` field.
- `{"type": "ticket_property", "key": "created_at", "operator": "date_before" | "date_after",
"value": "-3d"}` — see the date grammar below.

A multi-filter group ANDs its filters. For example, "email tickets from Big Corp opened in the
last week":

```json
{
  "label": "Big Corp (fresh)",
  "filters": [
    { "type": "ticket_property", "key": "channel_source", "operator": "in", "value": ["email"] },
    { "type": "ticket_property", "key": "email_from", "operator": "icontains", "value": "@bigcorp.com" },
    { "type": "ticket_property", "key": "created_at", "operator": "date_after", "value": "-1w" }
  ]
}
```

### The created_at date grammar

Strict, validated on save:

- **Relative**: `-N<unit>` with unit `h`/`d`/`w`/`m`/`y` (hour/day/week/month/year), N 1..1000, and
  an optional **case-sensitive** `Start` or `End` suffix — e.g. `-3d`, `-12h`, `-1mStart`, `-1yEnd`.
  Nothing looser: no `3d`, `+3d`, `-3days`, `-3dstart`. Bare `-3d` is a **rolling** window (now
  minus 3 days, time-of-day kept), resolved at query time; `Start`/`End` snap to the start/end of
  the unit (weeks start on Sunday).
- **ISO datetime**: zero-padded `YYYY-MM-DD`, optionally with a time and offset — `2026-07-01`,
  `2026-07-01T12:00:00Z`.

## The tools

1. **conversations-ticket-groups-get** — always read first. Returns the saved groups and
   `customized` (false = following the built-in examples), plus a settings deep link.
2. **conversations-ticket-groups-update** — replaces the **whole** list, so include every group
   the user wants to keep, in the exact order. Without `confirm:true` it returns a preview and
   saves nothing — show the preview to the user, get their go-ahead, then re-run with
   `confirm:true`. Pass `groups: null` to reset the team to the built-in examples.

Users can also edit the groups themselves at Settings → Support → Ticket groups (drag to reorder),
so for a one-off tweak it's fine to just link them there instead.

## Example flow

User: "Add a VIP tier above everything else, matching the `vip` tag."

1. Call `conversations-ticket-groups-get` → say it returns `[Enterprise, Free plan]`.
2. Call `conversations-ticket-groups-update` with
   `groups: [{label: "VIP", filters: [{type: "ticket_tags", operator: "any_of", value: ["vip"]}]}, {label: "Enterprise", ...existing filters}, {label: "Free plan", ...}]`
   (no `confirm`) → show the user the preview.
3. On their confirmation, re-run with `confirm: true`.

## Gotchas worth telling users about

- The update replaces the full list — dropping a group from the payload deletes it. Always start
  from the current groups.
- Tags come from the team's ticket-tagging (often set by workflows). A tags-based group only ranks
  what the tags already say; if tickets are missing tags, they'll pool in the first group.
- Limits enforced on save: at most 50 groups, 10 filters per group, 100 values per filter, labels
  ≤ 100 chars, string values ≤ 200 chars, no duplicate labels.
- Overlapping groups are fine (first match wins), but the order between them decides everything —
  put the more specific group first.
- Sorting by ticket group in the UI shows section headers with per-group match counts across the
  whole filtered result set, including "zero tickets match current filters" for empty groups.
