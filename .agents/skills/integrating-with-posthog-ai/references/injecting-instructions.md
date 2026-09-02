# Injecting custom instructions

`type: 'instructions'` is the one reserved item type. Its `value` lands in `<posthog_trusted_context>` — guidance the agent is told to follow — instead of the untrusted block everything else goes to.

Use it to say what the user has open, which tools to prefer, and what "this thing" means on this page.

```ts
const ISSUES_QUERY_TOOL_CONTEXT_ITEM: AttachedContextItem = {
  type: 'instructions',
  hidden: true,
  value:
    'The user has the error tracking issue list open. When you call query-error-tracking-issues-list, the filters ' +
    'from your query (filter group, status, date range, search, ordering, assignee) are also applied to the open ' +
    'page, so the user sees matching issues both in this chat and on screen.',
}
```

Set `hidden: true` unless the instruction is something the user should see as a chip. Register it exactly like any other context item — the type is the only difference.

## Trusted means static

**Instructions must carry only your own build-time strings.** Never a user-entered name, an ingested value, or a string interpolated from one. Trusted context is direction the agent follows, so a crafted entity name there is a prompt injection against whoever reads the thread next — including other users on a shared task.

Programmatic and user data go on ordinary untrusted items. That split is the whole point of having two blocks.

If an instruction needs to point at something that varies — which id is open, which step is selected — do not interpolate it. Put the pointer on an untrusted item and have the static instruction refer to it **by field name**:

```ts
// Static. Names the field, carries no id.
value: `The user has the email editor open. The hog_flow_editor_state item's editing_email_action_id field names ` +
  `the open action; the latest editor state wins over anything earlier in the conversation.`
```

There is a second reason this matters. Instructions dedupe per task by **exact text**, so a varying id inside an instruction would be pruned on a reopen: open A, open B, reopen A, and B's stale pin is the newest surviving text. The editor-state item's value changes whenever the state does, so it always re-sends. `products/workflows/frontend/Workflows/workflowAgentContext.ts` documents both reasons at the call site.

If you truly must interpolate an identifier, allowlist its shape first — that file gates on `SAFE_ACTION_ID = /^[A-Za-z0-9_-]{1,128}$/` before any action id reaches trusted text, because action ids are arbitrary strings a workflow author controls.

## Injecting a skill and a tool catalog

**The two things worth putting in trusted context are your product's MCP tool names and its skills** — both of which already exist in the repo as build-time sources, which is exactly what makes them safe here.

- **Skills** come from the skill build pipeline in `products/*/skills/`. Your product's skills are already written, linted, and shipped to external agents; embedding one gives the web agent the same job-to-be-done guidance a Claude Code user gets. See `/writing-skills`.
- **MCP tool names and descriptions** come from your `products/<name>/mcp/tools.yaml` and the generated schemas. Naming the tools up front stops the agent burning turns on discovery. See `/implementing-mcp-tools`.

The richest use of trusted context is handing the agent both up front, so it does not spend turns discovering tools or reading skill files. `workflowAgentContext.ts` attaches four things:

1. A **preamble** telling the agent the skill and tool catalog are already embedded, so it should call tools directly rather than go looking.
2. The **skill content** itself, embedded as a string.
3. One instruction item **per MCP tool**, each carrying the tool's name and description.
4. A visible `type: 'skill'` chip so the user can see (and detach) what was attached.

### Generate the payload, never hand-copy it

All of it comes from `products/<product>/frontend/generated/agentContext.ts`, built by
`services/mcp/scripts/build-scene-tool-context.ts` and regenerated with `hogli build:openapi`. That script
reads two sources at build time:

- `products/<product>/mcp/*.yaml` — which tools are enabled, with their live descriptions.
- `products/<product>/skills/<skill>/` — the skill markdown, named file by file (`SKILL.md` plus whichever
  `references/*.md` are worth embedding).

To get one for your product, add an entry to that script's config: the output path, the tool YAML files with
a const name each, and the skill directories with the files to embed. The workflows entry is the model.

This is what makes the payload safe as trusted text: it is our own source, checked into the repo, not runtime
data. It is also what keeps it honest — hand-copied skill text or a pasted tool description silently drifts
from the skill or tool it claims to describe, and nothing catches it.

Tie the whole bundle together with a shared `dismissGroup` so the visible chip and the hidden payload detach as one.

## Conditional instruction sets

Instructions can change with what the user is doing on the page. The same file attaches an extra bundle only while the email takeover is open, and gates it on the URL parameters actually resolving to a real email action — a lingering `?editor=email` param must not flip the agent into the wrong framing. Compute the condition properly and pass it down, rather than trusting a query string.
