---
name: using-the-console-ui
description: How to drive PostHog Code's read panel as the user works with you — focus_* etiquette, when to call toast, how to handle 'follow mode' being off. Load when the session client kind is `posthog-code`.
agents:
  - agent-builder
---

# Skill — using the PostHog Code UI

How to drive PostHog Code's read panel while you work, so
the user always sees what you're working on. Load when
`client.kind` is `posthog-code`.

## The client tools you have

| Tool                 | What it does                                                                               | When to call                                                                               |
| -------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| `focus_tab`          | Switch the agent detail panel between `overview` / `configuration` / `sessions`            | Coarse navigation between the three top-level views                                        |
| `focus_file`         | Open one bundle file in the configuration panel                                            | About to read or edit a specific file                                                      |
| `focus_revision`     | Open one revision in the configuration panel                                               | About to inspect / diff a specific revision                                                |
| `focus_session`      | Open one session in the sessions panel                                                     | About to fetch a session's conversation or event log                                       |
| `focus_spec_section` | Jump to a section of the spec (`tools` / `skills` / `triggers` / `secrets` / `limits`)     | Discussing one part of the spec specifically                                               |
| `toast`              | Surfaces a transient status notification in PostHog Code                                   | Sparingly — for long-running tool calls, or to flag something the user should look at      |
| `set_secret`         | Render an inline form for the user to enter a secret value, scoped to one key on one agent | Whenever you need a credential set or rotated. See `secrets-and-integrations` for the loop |

All are no-ops if the client doesn't handle them; the runner hides
them from your tool surface. If they're in your tool list, PostHog Code
is on the other end.

`set_secret` is the first **render-style, interactive** client tool — instead
of running a synchronous handler, PostHog Code mounts a UI inside
the tool-call card and the runner parks the session while the user
fills it in. Your call returns a synthetic `{queued:true, interactive:true, call_id}`
envelope immediately; end the turn cleanly and the real outcome
arrives as a wake message on a fresh turn (see
the `secrets-and-integrations` playbook Path A for the full loop). Tools
that need user input belong here; tools the host can fulfill
silently (navigation, toasts, context reads) stay synchronous.

## `focus_*` etiquette

**Call the right one before the tool call that operates on the
resource**, not after. The user wants the panel to load _as_ you
start working, not after the work is done.

Sequence:

1. Tell the user what you're about to do (one line)
2. The matching `focus_*` to the resource (only if you have
   the id / path in hand — otherwise skip it)
3. Make the actual MCP / native tool call(s)
4. Report back

The five focus tools and when to use each:

| Tool                 | Args (slug always required)                                                                      | Use when                                                |
| -------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------- |
| `focus_file`         | `{ slug: "<agent>", path: "skills/research.md" }`                                                | Reading or editing a specific bundle file               |
| `focus_revision`     | `{ slug: "<agent>", revisionId: "<uuid>" }`                                                      | Reading or editing a revision's spec / bundle overall   |
| `focus_session`      | `{ slug: "<agent>", sessionId: "<uuid>" }`                                                       | Debugging or watching a session                         |
| `focus_spec_section` | `{ slug: "<agent>", section: "tools" / "skills" / "triggers" / "secrets" / "limits" }`           | Discussing a specific part of the spec                  |
| `focus_tab`          | `{ slug: "<agent>", tab: "overview" / "configuration" / "connections" / "sessions" / "memory" }` | Coarse navigation when you don't yet have a specific id |

**`slug` is required on every focus call.** The dock does NOT infer
the target from whatever page the user happens to be on — the user
navigates while you're thinking, and silently following the URL is
a fast way to misroute. If you don't know the slug, call
`get_context` or `posthog__agent-applications-list` first.

For a multi-file flow (e.g. inspecting `agent.md` then a skill
then the live session), call focus **before each transition**.
Don't focus once and assume the user followed your text-based
navigation.

## Handle the focus result

Every `focus_*` returns either:

- `{ focused: true, kind: ..., ... }` — the panel loaded; the
  user saw it
- `{ focused: false, reason: "user_paused_follow" }` — the user
  has "Follow the agent" turned off; the panel didn't change
- `{ focused: false, reason: "missing_slug ..." }` — you didn't
  pass `slug`. Look it up via `get_context` or
  `posthog__agent-applications-list` and retry. Don't keep firing without
  it; the dispatcher will keep refusing.

When `focused: false`, **adapt**:

- Spell out the resource path in text (`"see skills/research.md
in the bundle"`)
- Don't keep firing focus events — they're being ignored on
  purpose
- Note it once ("Follow-mode is off, so I'll narrate paths instead.")

When `focused: true`, **keep your text concise** — the user can
see what you see, so don't re-describe it. "Read `agent.md`,
turn 1 makes the agent skip the slack post on weekends" is
enough; don't paste the whole file.

## `toast` etiquette

Toasts are intrusive. Use them only for:

- **Long-running work** the user should know about: "Running 5
  test cases — this will take ~30s"
- **State changes outside their current view**: "Revision r_new
  promoted to live"
- **Errors that need their attention** but don't block the
  conversation: "Slack integration token expired — re-auth at
  <link>"

Don't toast for:

- Status updates that fit in the chat ("Reading agent now…")
- Progress on a quick call (anything under 5s)
- Things the user is actively watching (they don't need a toast
  about something they can see)

Toasts are silent for the model — they're a UI side effect, not
a tool result you should react to.

## When the user steers via the read panel

PostHog Code lets the user click around the read panel
independently. If the user says "I just opened revisions, can
you compare r_old and r_new?", they have navigated themselves —
you can pick up from there without focusing first. But still
focus before YOUR next action.

## Combining focus + acknowledgement

Pattern: one short text line + one focus call + the actual work,
all in the same turn.

Example:

> Opening `weekly-digest`'s live revision, pulling its spec +
> system prompt.
>
> [calls `focus_revision` with `{ revisionId: 'r_live123' }`]
>
> [calls `posthog__agent-applications-revisions-retrieve`]
> [calls `posthog__agent-applications-revisions-system-prompt`]
>
> Spec is 4 tools, 3 skills, cron trigger every Monday 09:00.
> Want me to walk through the skills, or jump to recent sessions?

The user's experience: text appears, panel transitions to the
revision view, a moment later the chat shows the summary. Three
beats, all in one turn.

## Deep links PostHog Code understands

PostHog Code reads its full view state from URL params, so you can hand
the user a link to a specific surface and trust they'll land where you
want them to. The two patterns that are load-bearing today:

| Goal                                    | URL                                                                          | Notes                                                                                                                                          |
| --------------------------------------- | ---------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Open the agent's connections / secrets  | `/agents/<slug>/connections`                                                 | Just lands on the tab. Use as a fallback when there's no specific key yet.                                                                     |
| Open the secret editor for one key      | `/agents/<slug>/connections?edit_secret=<KEY>`                               | Opens the modal pre-targeted. Don't `focus_tab` to the connections tab and _also_ tell them to edit — pick one channel.                        |
| Same, with a callback into THIS session | `/agents/<slug>/connections?edit_secret=<KEY>&callback_session=<session_id>` | PostHog Code fires a synthetic `[system]` user turn back to `<session_id>` after they save. You wait silently. See `secrets-and-integrations`. |

Get `<session_id>` from `get_context` — it's the `session_id`
field on the envelope. Don't try to derive it any other way; you
don't have stable access to it otherwise.

When you render the link in chat, use a markdown link so the user can
one-click it. Don't paste the URL bare — they'll often miss it in a
wall of text.

## When NOT to focus

- The user just asked you to summarize without context-switching
  ("just give me the slug list, don't open anything")
- The thing you're looking at isn't a UI-representable resource
  (e.g. a transient computation, an in-memory inference)
- You're mid-debug and the user has explicitly turned follow-mode
  off — respect it

## Errors from focus

If a `focus_*` call returns `client_tool_unsupported` (unexpected
— should have been hidden from your surface), behave as if you
got `focused: false`. Don't crash; fall back to text narration.
This shouldn't happen, but a buggy PostHog Code version might.

## The "screen-sharing" mental model

Treat `focus_*` as moving a cursor on a shared screen. Every
action you take, the user should be able to see _where_ you took
it. The chat is the audio narration; the read panel is the
screen. Together they make the whole interaction legible —
without focus, the chat reads like talking to someone whose
screen is off.
