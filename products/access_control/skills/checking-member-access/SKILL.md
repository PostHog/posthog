---
name: checking-member-access
description: >
  Explains what a member or a role can do in a PostHog project, using the access control MCP tools.
  Use when the user asks what someone can see or edit, who can edit dashboards or feature flags, why a
  member can or cannot open a dashboard, notebook or table, what a role grants, which properties are hidden
  from someone, or how the project's default access is set. Covers how the stored rule, the enforced level
  and the inherited access relate, what the null values mean, which tool answers which question, and when
  the answer needs the role tools too.
---

# Checking member access

Use this skill to answer "what can this person do here?" from the access control tools. The tools return
the enforced level and where it comes from. This skill is for reading them correctly, because the response
does not carry the rules that produced it.

## When to use this skill

- "What can Alex do in this project?" / "Can Alex edit feature flags?"
- "Who can edit dashboards?" / "Who has no access to session replay?"
- "Why can't Alex open this dashboard?" / "Which tables is this role restricted from?"
- "Which properties are hidden from support?"
- "What does the `analyst` role grant?" / "What is the default access in this project?"

Not for changing rules. The read tools cannot write, and the settings page is where rules are edited.

## How access resolves

- **Scopes.** The project itself, then each tool (`dashboard`, `insight`, `feature_flag`, `notebook`,
  `experiment`, `warehouse_objects`, and so on), then single objects inside a tool, then person and event
  properties. The tool names are the keys of `resources` in a members-list entry.
- **Levels.** Project: `member` < `admin`. Tools and objects: `none` < `viewer` < `editor` < `manager`.
  Properties: `none` < `read` < `read_write`, and every property is `read_write` unless a rule exists.
  `minimum` and `maximum` per tool, on `defaults-get`, are the bounds a rule can set; a tool with
  `minimum` `viewer` can never be set to `none`.
- **Subjects.** A rule belongs to one member, one role, or everyone (the default).
- **Bypasses.** Organization admins and owners (`organization_level` 8 or 15) pass every rule. So does
  the creator of an object, for that object. The organization's own membership can grant project access
  when the project is open to all members.
- **Two resolution modes.** Organizations resolve rules either most-specific-first (member rule, then
  role rules, then default, and object rule before tool rule) or legacy (the highest of the member's own
  rule and role rules wins). The tools do not say which mode applies. The server
  already applied it. So **trust `effective_access_level` and never recompute it from the stored
  rules.** If the user asks why, explain from `inherited_access`, not from your own precedence.

## Available tools

| Tool                                              | Answers                                                                                  |
| ------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `posthog:access-control-members-list`             | Every member's enforced access to the project and each tool. `member_id` narrows to one. |
| `posthog:access-control-roles-list`               | The same per role. `role_id` narrows to one.                                             |
| `posthog:access-control-defaults-get`             | The project baseline, and which tools accept rules on single objects.                    |
| `posthog:access-control-member-objects-list`      | One member's own rules on single objects.                                                |
| `posthog:access-control-member-properties-list`   | One member's own property rules.                                                         |
| `posthog:access-control-role-objects-list`        | One role's rules on single objects.                                                      |
| `posthog:access-control-role-properties-list`     | One role's property rules.                                                               |
| `posthog:access-control-default-objects-list`     | Object rules that apply to everyone.                                                     |
| `posthog:access-control-default-properties-list`  | Property rules that apply to everyone.                                                   |
| `posthog:org-members-list`                        | Membership ids, names and organization levels. Not access.                               |
| `posthog:roles-list`, `posthog:role-members-list` | Role ids, and who is in a role.                                                          |

All access control tools take an optional project id and default to the active project.

## Workflow

1. **Find the subject id.** `member_id` is the organization membership id: the `id` from
   `org-members-list`, or `organization_membership_id` from `members-list`. It is not the user id and not
   the user uuid. `role_id` is the `id` from `roles-list`.
2. **Ask the tool-level question first.** One call to `members-list` with `member_id` answers most
   questions. Read `effective_access_level` for the project and for the tool the user named.
3. **Explain the level from `inherited_access`.** See the table below. Only mention the stored
   `access_level` when it differs from the enforced level.
4. **Go to objects or properties only when the question names one.** "Can Alex open dashboard 42?"
   needs `member-objects-list`. "Can Alex see `email`?" needs `member-properties-list`.
5. **Include role rules for object and property questions.** Member lists hold only the member's own
   rules. Rules a role sets on an object or property are on the role tools. Get the member's roles from
   `role-members-list` (one call per role in `roles-list`), then `role-objects-list` or
   `role-properties-list` per role. This fans out. Tell the user how many roles you would walk and ask
   before doing it for an organization with many roles.
6. **"Who can ..." questions** are `members-list` without `member_id`, filtered on
   `resources.<tool>.effective_access_level`. The response is every member times every tool and has no
   pagination. For a large organization, ask which people the user cares about first, or answer per
   member.

## Reading one entry

| Field                             | Meaning                                                                                                                                                                                              |
| --------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `access_level`                    | The subject's own stored rule for this scope. `null` means no rule of its own.                                                                                                                       |
| `effective_access_level`          | What is enforced. `null` means the organization is not entitled to this tool, not "no access".                                                                                                       |
| `inherited_access`                | The level the subject falls back to without a rule of its own, and where it comes from. `null` when nothing supplies one.                                                                            |
| `inherited_access.source`         | `resource` or `parent_resource` for a tool rule, `object` or `parent_object` for an object rule, `system_default` for the built-in default, `org_admin`, `creator` or `org_membership` for a bypass. |
| `inherited_access.source_subject` | `member`, `role` or `default`: whose rule supplied it. `null` when a bypass or the built-in default did.                                                                                             |

How to phrase the answer:

- `source` is `org_admin`: "Alex is an organization admin, so every rule is bypassed." The org level is
  the answer; the stored rules are irrelevant.
- `access_level` is set and equals `effective_access_level`: "Alex has an explicit rule: editor."
- `access_level` is `null` and `source_subject` is `role`: "Alex gets editor from a role rule." The
  role's name is not in the entry; `roles-list` has it if the user wants it.
- `access_level` is `null` and `source_subject` is `default`: "Alex has the project default: viewer."
- `source` is `system_default`: "No rule is set anywhere, so the built-in default applies."
- `effective_access_level` is `null`: "This organization's plan does not include this tool."

## Gotchas

- An empty object or property list means no rules of that kind, not no access. The tool-level entry
  still applies.
- A member missing from `members-list` is not proof of no access. A caller who is not an organization
  admin, in an organization where members cannot see each other, only sees members with project-scoped
  access.
- `can_edit` on the members and roles lists describes the caller, not the subject: whether the person
  running the tool may change rules.
- `available_project_levels` and `available_resource_levels` are the vocabulary, lowest first. Use them
  to compare levels instead of assuming an order.
- `object_rule_resources` on `defaults-get` lists the tools that accept rules on single objects. A tool
  not in that list has no object rules to look for.

## What to say back

Lead with the enforced level and where it comes from, in one sentence per scope the user asked about.
Give the stored rule only when it differs. Name the follow-up you did not do, for example role object
rules you did not walk, so the user knows the answer's limit.
