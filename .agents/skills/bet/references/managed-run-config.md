# `run_config` for managed bets

A `managed` bet's `run_config` field is `{command, env, caps}`:

```json
{
  "command": "echo hello",
  "env": { "SOME_VAR": "value" },
  "caps": { "max_depth": 3, "max_children": 3, "max_cost": 10 }
}
```

`command` runs in a sandbox as the root node. It's a shell command, not agent
logic — whatever orchestrator the user wants to run inside it is their
concern; Foundry only provisions the sandbox, runs the command, and watches
its stdout for structured events.

## Spawning children (recursive node trees)

A running node's command declares a child by invoking `foundry-event` — a
tiny helper Foundry installs into every node's sandbox at
`/usr/local/bin/foundry-event` — with a **base64-encoded JSON payload**:

```sh
foundry-event "$(echo -n '{"type":"spawn_child","node_id":"child-a","command":"...","runner":"claude-code","cost":1}' | base64 -w0)"
```

Base64, not raw JSON in shell quotes: a spawned child's own `command` can
itself contain further `foundry-event` calls (recursion), and shell-quoting
rules don't compose across nesting levels — base64 has no shell-special
characters at any depth, so it survives being embedded as a JSON string value
inside an outer command however many levels deep.

**The payload must be compact, single-line JSON before encoding.**
`foundry-event`'s installed script does `printf '%s%s\n' '##FOUNDRY_EVENT## '
"$(echo "$1" | base64 -d)"`, and the activity that parses a node's stdout
(`_parse_foundry_events` in `products/foundry/backend/temporal/activities.py`)
only recognizes lines that _start_ with the `##FOUNDRY_EVENT##` prefix. If
the JSON you encode is pretty-printed (e.g. `jq -n` without `-c`, or
`json.dumps(..., indent=2)`), the decoded output spans multiple lines — only
the first line carries the prefix, and it's an incomplete JSON fragment (like
`{`), so the event is silently dropped and the child never spawns. This was
a real bug hit while building this skill's test harness. Always encode with
compact JSON: `jq -nc '...'` (bash) or `json.dumps(..., separators=(",",
":"))` (python), never the pretty-printed default.

Compact JSON still contains an escaped `\n` (two characters, backslash then
`n`) for every real newline inside a multi-line `command` value — e.g. a
`spawn_child` payload whose child runs an actual multi-step shell script,
like the test-writer → builder pattern below. The helper script uses
`printf '%s'` rather than `echo` specifically so those two-character escapes
survive unmolested to the parser: a `/bin/sh` that's dash (the sandbox
image's shell) has an `echo` builtin that interprets backslash escapes by
default, so `echo`-ing the decoded payload would turn every `\n` back into a
_real_ newline and reintroduce the exact same multi-line-JSON breakage —
this was a second, deeper variant of the same bug class, latent since
iteration 2 because every prior demo's `command` value happened to be a
single line. If you ever need to reinstall or hand-roll this helper, keep
`printf`, not `echo`.

Payload types (`type` field):

- `spawn_child`: `{node_id, parent_node_id?, command, runner?, cost?, max_cost?, max_depth?, max_children?}`
- `knowledge_published`: `{repo, ref?, path?, title?}`
- `artifact_ready`: `{repo_url, ref, base_ref, pr_url?}` — see "Triggering the gauntlet" below.
- `note`: `{message}`

## Worked example: root → 2 children → 1 grandchild

Bash, building the nested payloads bottom-up (each shell function argument
is compact-JSON-then-base64):

```sh
fe_spawn() { # node_id command runner cost
  jq -nc --arg node_id "$1" --arg command "$2" --arg runner "$3" --argjson cost "$4" \
    '{type:"spawn_child", node_id:$node_id, command:$command, runner:$runner, cost:$cost}' | base64 -w0
}

grandchild_cmd='echo "grandchild doing trivial work"'
b_spawn=$(fe_spawn "grandchild" "$grandchild_cmd" "claude-code" 1)
child_b_cmd="echo \"child-b doing trivial work\" && foundry-event ${b_spawn}"

a_spawn=$(fe_spawn "child-a" 'echo "child-a doing trivial work"' "claude-code" 1)
b_spawn_top=$(fe_spawn "child-b" "$child_b_cmd" "claude-code" 1)
root_cmd="echo \"root doing trivial work\" && foundry-event ${a_spawn} && foundry-event ${b_spawn_top}"
```

`root_cmd` is then `run_config.command`. Each `foundry-event` call is
unquoted in the outer command on purpose — a base64 string has no whitespace,
so word-splitting never touches it.

## Caps

`caps.max_depth` / `max_children` / `max_cost` are enforced by the workflow
at every level; a spawn that would violate a cap cancels that subtree and
emits a `budget.exceeded` event instead of spawning. Costs decrement down the
tree from the value set on the root.

## Memory in managed sandboxes

If the bet's `memory_repo_url` is set, it's `git clone --depth 1`'d into
`/memory` in every node's sandbox before `command` runs. An unreachable repo
degrades to a note in the node's output rather than failing the run.

## Triggering the gauntlet: test-writer → builder → artifact_ready

The gauntlet (ADR 4) needs a checked-out artifact — `{repo_url, ref, base_ref}`
— to diff and run checks against. A managed bet's own `run_config.command`
is what produces that artifact, by convention, not by any new machinery:

1. **Test-writer node** (optional, but this is the whole point of
   `gate_config.protected_paths`): the root (or a first child, `runner:
"test-writer"`) clones the bet's demo/fixture repo, writes acceptance
   tests under whatever prefix `protected_paths` names (e.g.
   `tests/acceptance/`), commits, and pushes a base ref (a branch or tag —
   this becomes `base_ref`).
2. **Builder node** (`runner: "builder"`), spawned as a child of the
   test-writer step: checks out that base ref, implements the change on a
   new branch, commits, and pushes — this branch becomes `ref`.
3. Whichever node finishes last emits `artifact_ready` with
   `{repo_url, ref, base_ref}` (and `pr_url` if the demo also opens a PR).
   If `gate_config.checks` is non-empty and the `foundry-reviewhog-gate` flag
   is on for the team, this is what makes the automatic gauntlet fire for a
   managed bet — no manual `gate.result` needed.

A builder that edits a file under `protected_paths` (the sabotage case) still
produces a valid artifact — the gauntlet catches it structurally via the
`protected_paths` check, not by the builder's own honesty. That's the
Uncle-Bob invariant this whole design exists for: don't rely on the builder
grading its own homework.

For `external` bets, the orchestrator just POSTs `artifact.ready` directly
via the events API instead of this in-sandbox helper — same payload shape,
same trigger condition.
