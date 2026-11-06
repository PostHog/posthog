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

## Naming a skill and a tool catalog

**The two things worth putting in trusted context are your product's skill names and its MCP tool names** — both already exist in the repo as build-time sources, which is exactly what makes them safe here.

- **Skills** come from the skill build pipeline in `products/*/skills/`. Every product skill is installed into the agent's sandbox, so the harness already lists it by name and description and loads the body in one call. See `/writing-skills`.
- **MCP tool names** come from your `products/<name>/mcp/tools.yaml`. The agent already reaches every tool through the exec MCP tool, and `info <tool>` returns the full input schema. Naming the tools up front stops the agent burning turns on discovery. See `/implementing-mcp-tools`.

`workflowAgentContext.ts` attaches two things for this:

1. One static **preamble** instruction that tells the agent which skill to load before its first tool call and which exec commands cover the product (the `workflows-*` prefix plus the handful that matter most).
2. A visible `type: 'skill'` chip so the user can see (and detach) what was attached.

### Name it, do not embed it

Do not embed skill markdown or per-tool descriptions into the payload. The context block rides on every message, so a skill body costs tens of thousands of tokens per task chain, and it duplicates a source the sandbox already has. It also needs codegen and a CI drift check to stay honest, and the copy still diverges from the rendered skill the sandbox installs. A skill name and a tool name are stable identifiers the agent resolves itself.

Keep the tool names you do mention in sync with the product YAML: a renamed tool turns the instruction into a dead pointer, and nothing catches it except the agent failing its first call.

Tie the whole bundle together with a shared `dismissGroup` so the visible chip and the hidden instruction detach as one.

## Conditional instruction sets

Instructions can change with what the user is doing on the page. The same file attaches an extra bundle only while the email takeover is open, and gates it on the URL parameters actually resolving to a real email action — a lingering `?editor=email` param must not flip the agent into the wrong framing. Compute the condition properly and pass it down, rather than trusting a query string.
