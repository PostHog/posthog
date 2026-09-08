---
name: checking-member-access
description: >
  Explains what a member or a role can do in a PostHog project, using the access control MCP tools.
  Use when the user asks what someone can see or edit, who can edit dashboards or feature flags, why a
  member can or cannot open a dashboard, notebook or table, what a role grants, which properties are hidden
  from someone, or how the project's default access is set. Covers what each level means, how the stored
  rule, the enforced level and the inherited access relate, what the null values mean, which tool answers
  which question, and when the answer needs the role tools too.
---

# Checking member access

Use this skill to answer "what can this person do here?" from the access control tools. The tools return
the enforced level and where it comes from. This skill is for reading them correctly.

## When to use this skill

- "What can this member do in this project?" / "Can this member edit feature flags?"
- "Who can edit dashboards?" / "Who has no access to experiments?"
- "Why can't this member open this dashboard?" / "Which tables is this role restricted from?"
- "Which properties are hidden from the support role?"
- "What does the `analyst` role grant?" / "What is the default access in this project?"

Not for changing rules. The read tools cannot write, and the settings page is where rules are edited.

## Plan availability

- Free and pay-as-you-go plans have no access control. Every level resolves to the PostHog default with
  `source` `system_default`, and any rule the tools return has no effect. Say so, and stop.
- Boost and Scale include the default levels and rules for single members on the project, on tools, on
  objects and on properties.
- Roles exist on every plan, but role rules count for access only on Enterprise. On other plans a role
  rule the tools return has no effect, and a member's roles never change the enforced level.
- The tools do not say which plan the organization is on. A `source_subject` of `role` anywhere in a
  `members-list` result proves that role rules count. Without that, ask the user whether the organization
  is on Enterprise before walking roles in step 4 of the workflow.

## How access resolves

- **Scopes.** The project itself, then each tool (`dashboard`, `insight`, `feature_flag`, `notebook`,
  `experiment`, `warehouse_objects`, and so on), then single objects inside a tool, then person and event
  properties. The tool names are the keys of `resources` in a members-list entry.
- **Project levels.** `member` can view and edit the resources their other rules permit. `admin` can also
  edit project settings, manage the project's access rules, and delete the project.
- **Tool and object levels.** `none` cannot view. `viewer` can view but not change. `editor` can view and
  change. `manager` can also manage the access rules of the tool or object. Order: `none` < `viewer` <
  `editor` < `manager`.
- **Property levels.** `none` hides the property. `read` shows it. `read_write` also allows edits. Every
  property is `read_write` unless a rule exists.
- **Bounds.** `minimum` and `maximum` per tool, on `defaults-get`, are the levels a rule can set. A tool
  with `minimum` `viewer` can never be set to `none`.
- **Subjects.** A rule belongs to one member, one role, or everyone in the project (the default).
- **Organization admins and owners** have full access to everything in every project. No rule applies to
  them. `organization_level` is a number: 1 member, 8 admin, 15 owner.
- **Creators** have full access to the objects they created, and only those. A member with `viewer` on
  dashboards can still edit the dashboard they created, and cannot edit the others.
- **Two resolution modes.** Organizations resolve rules either most-specific-first (member rule, then
  role rules, then default, and object rule before tool rule) or legacy (the highest of the member's own
  rule and role rules wins). The tools do not say which mode applies. The server already applied it. So
  **trust `effective_access_level` and never recompute it from the stored rules.** If the user asks why,
  explain from `inherited_access`, not from your own precedence.

## Available tools

| Tool                                              | Returns                                                                                          |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `posthog:access-control-members-list`             | Every member's enforced access to the project and to each tool. `member_id` narrows to a member. |
| `posthog:access-control-roles-list`               | The same per role. `role_id` narrows to a role.                                                  |
| `posthog:access-control-defaults-get`             | The project baseline, and which tools accept rules on single objects.                            |
| `posthog:access-control-member-objects-list`      | The object rules set for a member: every object with a rule for that member.                     |
| `posthog:access-control-member-properties-list`   | The property rules set for a member.                                                             |
| `posthog:access-control-role-objects-list`        | The object rules set for a role.                                                                 |
| `posthog:access-control-role-properties-list`     | The property rules set for a role.                                                               |
| `posthog:access-control-default-objects-list`     | The object rules that apply to everyone in the project.                                          |
| `posthog:access-control-default-properties-list`  | The property rules that apply to everyone in the project.                                        |
| `posthog:org-members-list`                        | Membership ids, names and organization levels. No project access details.                        |
| `posthog:roles-list`, `posthog:role-members-list` | Role ids, and who is in a role.                                                                  |

All access control tools take an optional project id and default to the active project.

## Workflow

1. **Find the subject id.** `member_id` is the organization membership id: the `id` from
   `org-members-list`, or `organization_membership_id` from `members-list`. It is not the user id and not
   the user uuid. `role_id` is the `id` from `roles-list`.
2. **Tool-level questions need one call.** "Can this member view dashboards?" or "What access to feature
   flags does this member have?" is `members-list` with `member_id`. `effective_access_level` for that tool
   is the complete answer. It already includes the member's roles, the project default and the bypasses.
3. **Explain the level from `inherited_access`.** See the table below. Only mention the stored
   `access_level` when it differs from the enforced level.
4. **Object and property questions need more calls.** "Can this member open dashboard 42?" or "Can this
   member see `email`?" cannot be answered from the tool level alone. The member tools return only the
   rules set for that member. A role can set a rule on the same object or property, and the default lists
   hold the rules for everyone in the project. So call `member-objects-list`, `default-objects-list`, and
   `role-objects-list` for each of the member's roles from `role-members-list`. Properties work the same
   way with the properties tools. This fans out. Tell the user how many roles you would walk and ask before
   doing it for an organization with many roles.
5. **No rule on the object or property** means the tool-level answer from step 2 applies.
6. **"Who can ..." questions** are `members-list` without `member_id`, filtered on
   `resources.<tool>.effective_access_level`. The response is every member times every tool and has no
   pagination. For a large organization, ask which people the user cares about first, or answer per
   member.

## Reading one entry

| Field                             | Meaning                                                                                                                                                                                                                                                                          |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `access_level`                    | The subject's own stored rule for this scope. `null` means no rule of its own.                                                                                                                                                                                                   |
| `effective_access_level`          | What is enforced. `null` means nothing resolves for this scope. It is not "no access".                                                                                                                                                                                           |
| `inherited_access`                | The level the subject falls back to without a rule of its own, and where it comes from. `null` when nothing supplies one.                                                                                                                                                        |
| `inherited_access.source`         | `resource` or `parent_resource` for a tool rule, `object` or `parent_object` for an object rule, `system_default` for the PostHog default. `org_admin` and `creator` are the bypasses described above. `org_membership` appears only when the object is the organization itself. |
| `inherited_access.source_subject` | `member`, `role` or `default`: whose rule supplied it. `null` when a bypass or the PostHog default did.                                                                                                                                                                          |

How to phrase the answer:

- `source` is `org_admin`: "This member is an organization admin and has full access to everything." The
  stored rules do not apply to them.
- `access_level` is set and equals `effective_access_level`: "This member has an explicit rule: editor."
- `access_level` is `null` and `source_subject` is `role`: "This member has editor access, based on a role."
  The role's name is not in the entry; `roles-list` has it if the user wants it.
- `access_level` is `null` and `source_subject` is `default`: "This member has viewer access, based on the
  project default."
- `source` is `system_default`: "No rule is set anywhere, so the PostHog default applies."
- `effective_access_level` is `null`: "Nothing resolves for this tool here." Do not read it as no access.

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
