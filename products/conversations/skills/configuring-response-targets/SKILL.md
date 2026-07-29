---
name: configuring-response-targets
description: >
  Configure a team's response-target ladder — the ordered, tag-based priority groups the support
  tickets list sorts and groups by. Use when the user wants to define, reorder, edit, or reset
  their ticket priority groups ("work Enterprise tickets before free-plan ones", "add a VIP tier",
  "change our triage order"), or asks why tickets sort the way they do under the Response target
  column.
---

# Configuring response targets

Response targets tell the Conversations tickets list which tickets to work first. A team defines an
ordered ladder of groups, each with a label and a set of ticket tags. Sorting the list by
**Response target** (`order_by=response_target` on `conversations-tickets-list`) orders tickets by
group (top group first), then by SLA deadline within each group (soonest first, no deadline last),
and renders a header per group with match counts. One click gives the team their "work next" order.

## How ranking works

- The ladder is stored per team in `conversations_settings.response_target_groups` as an ordered
  `[{label, tags[]}]` list. **List order is priority order** — first group is worked first.
- A ticket joins the **highest** group that matches any of its tags.
- Tag matching is **exact**: `urgent_billing` does not match a group on `urgent`. A tag may appear
  in only one group, and labels must be unique.
- Tickets matching **no** group rank with the **first** group. That's deliberate triage semantics:
  an untagged ticket needs eyes, not burial. Advise users to keep a "Triage"-style group at the top.
- A team with no saved ladder follows a small built-in example (Triage / Urgent / VIP).

## The tools

1. **conversations-response-targets-get** — always read first. Returns the saved ladder and
   `customized` (false = following the built-in examples), plus a settings deep link.
2. **conversations-response-targets-update** — replaces the **whole** list, so include every group
   the user wants to keep, in the exact order. Without `confirm:true` it returns a preview and
   saves nothing — show the preview to the user, get their go-ahead, then re-run with
   `confirm:true`. Pass `groups: null` to reset the team to the built-in examples.

Users can also edit the ladder themselves at Settings → Support → Response targets (drag to
reorder), so for a one-off tweak it's fine to just link them there instead.

## Example flow

User: "Add a VIP tier above everything else, matching the `vip` tag."

1. Call `conversations-response-targets-get` → say it returns `[Enterprise, Free plan]`.
2. Call `conversations-response-targets-update` with
   `groups: [{label: "VIP", tags: ["vip"]}, {label: "Enterprise", ...existing tags}, {label: "Free plan", ...}]`
   (no `confirm`) → show the user the preview.
3. On their confirmation, re-run with `confirm: true`.

## Gotchas worth telling users about

- The update replaces the full list — dropping a group from the payload deletes it. Always start
  from the current ladder.
- Tags come from the team's ticket-tagging (often set by workflows). The ladder only ranks what the
  tags already say; if tickets are missing tags, they'll pool in the first group.
- Limits enforced on save: at most 50 groups, 100 tags per group, labels ≤ 100 chars, tags ≤ 200
  chars, no duplicate labels, no tag in two groups.
- Sorting by Response target in the UI shows section headers with per-group match counts across the
  whole filtered result set, including "zero tickets match current filters" for empty groups.
