---
name: instrumenting-with-hogtrace
description: Use when the user asks to observe runtime behavior of a running Python service via hogtrace probes — installing, listing, inspecting, or uninstalling live debugger programs through the PostHog MCP. Covers writing hogtrace source (probes, predicates, captures, request-scoped variables, sampling), choosing probe points safely, installing programs, and querying the events they emit. Trigger on phrases like "install a hogtrace program", "add a probe to function X", "live debug this code", "see what arguments / locals / return value this function gets in prod", "trace requests through Y", or any mention of hogtrace, live debugger, runtime instrumentation, or DTrace-style probes for a PostHog-instrumented Python service.
---

# Instrumenting a Python service with hogtrace

Hogtrace is a DTrace-inspired probe language. You write small declarative programs that say "when function X is entered/exited, capture these values." The PostHog libdebugger runtime polls the project, installs your program, and the probes start emitting events the moment they fire.

All hogtrace work now happens inside a **debugging session**. A session is a notebook-style timeline: programs you install, events you pin, and your own narration are all entries on it, in order, so a human reviewing the session later can follow the investigation. You operate entirely through MCP — never edit application code, never restart the service.

## The job to be done

```text
1. Start a session                 (debugging-session-start)
2. Install probes                  (debugging-session-install-program)
3. Read events                     (debugging-session-program-events)
4. Note your reasoning             (debugging-session-add-entry, kind=note)
5. Pin informative events          (debugging-session-add-entry, kind=event_highlight)
6. Refine: install more / uninstall obsolete (atomically recorded on the timeline)
7. Close the session               (debugging-session-close, with conclusion_markdown)
```

The session timeline is the artifact. Treat notes as the running commentary a teammate would read — short, specific, hypothesis-driven. Treat event highlights as pinned exhibits. Don't bury insight in your own scratch context.

## Starting a session

`debugging-session-start` takes `title` (short, scannable) and `description` (a paragraph framing the goal). Do this **before** installing anything — every later tool call references `session_id`. Returns the new session with its id.

Sessions stay open until you close them. While open you can keep appending entries and installing/uninstalling programs.

## Probe-point fundamentals

A probe specifier is `provider:dotted.path:probe_point`. Today only the `fn` provider is supported.

```dtrace
fn:myapp.users.create_user:entry
fn:myapp.users.UserService.create:exit
fn:myapp.api.*:entry                  # wildcards allowed
```

The dotted path must resolve to a **callable importable in the target process**. The runtime walks prefixes downward (module then attribute). If nothing resolves, the probe is silently skipped and you get no events.

What the runtime **cannot** instrument: lambdas, closures captured at runtime, dynamically assigned instance attributes, builtins, C extensions. Confirm the import path before composing the probe — wrong path = no events.

## Choosing entry vs exit

| You want to see…                             | Use                                              |
| -------------------------------------------- | ------------------------------------------------ |
| Arguments being passed in                    | `:entry`                                         |
| Return value or whether it threw             | `:exit`                                          |
| Duration (start time on entry, diff on exit) | Both, joined via `$req.*`                        |
| State midway through                         | `:entry+N` (bytecode offset — niche, often skip) |

Exit probes get `retval` and `exception` (None on success). For "what did it return when it failed" use `:exit` with `/ exception != None /`.

## Writing the source

Keep it small. A typical first program is one or two probes:

```dtrace
fn:myapp.payments.process_payment:exit
/ exception != None /
{
    capture(args=args, exception=exception, user_id=$req.user_id);
}
```

Always prefer **named captures** (`capture(name=value, ...)`) — they show up as distinct properties on the event. Reserve `capture(args)` and `capture(locals)` for "I don't know what I'm looking for yet" exploration; name fields as soon as you know them.

Predicates filter at runtime cheaply — push as much filtering into them as possible. They can read `args`, `arg0..argN`, `kwargs`, `self`, `retval`, `exception`, and `$req.*`, plus `len(...)`, `rand()`, `timestamp()`. For high-traffic targets, sample: `/ rand() < 0.01 /` or `sample 1/100;` as first body statement.

For cross-probe state in the same request, use `$req.*` (thread-locally scoped to the request, cleared at request end). Unset reads return `None`.

For common shapes — request duration, slow-query capture, exception capture, conditional traces — see [patterns](./references/patterns.md). Full syntax in [language reference](./references/language.md).

## Installing the program

Use `debugging-session-install-program` with `session_id`, `code` (hogtrace source), and `description` (short specific explanation — "Trace failed payments to see exception types we're missing" beats "payment probe"). Returns the program `id` and atomically appends a `program_install` entry to the session timeline.

The runtime poller picks up the program on its next tick (~30s). **Arming is per-worker and asymmetric** — each Granian worker polls on its own cycle. Plan to wait **at least 60 seconds** after install before assuming the probe is wired up; longer for low-traffic targets. A request that lands on a not-yet-armed worker silently bypasses the probe.

## Watching for events

`debugging-session-program-events` returns recent probe-hit events for one program (by `program_id`), most recent first. Each event has `timestamp`, `probe_id`, `filename`, `line_number`, `function_name`, `locals` (your captures), and `stack_trace`.

If you see nothing after 60–90s:

1. Re-read the session with `debugging-session-show` and check the program's source.
2. The dotted path may not resolve in the running process.
3. The function may not be called in this window — low-traffic targets need patience.
4. The predicate may always evaluate false — try without the predicate to confirm probes are firing.

See [troubleshooting](./references/troubleshooting.md) for more.

## Narrating the session

After each interesting batch of events, append a `note` entry with `debugging-session-add-entry` (`kind=note`, `body_markdown=...`). Notes are how a human reading the session later reconstructs your reasoning — keep them dense and hypothesis-driven: what you expected, what you saw, what it implies, what you'll try next.

When specific events prove a point, pin them with a `event_highlight` entry: `kind=event_highlight`, `event_ids=[...uuids...]`, `caption="one-line summary"`. Pinned events become the durable exhibits of the session.

## Iterating

Programs are immutable after install — to change one, install a new program (and uninstall the old one with `debugging-session-uninstall-program` if its probes are now noise). Each install/uninstall is recorded on the timeline.

Prefer **adding more captures to a single broad program over many install/uninstall cycles.** Each uninstall→install round costs another ~60s arming window and can leave some workers stale. If you can predict the captures you'll want, install them all at once.

For "X happens the first time but not the second" bugs, capture named locals at `:exit` and diff two consecutive events — see [cross-call diff](./references/patterns.md#cross-call-diff--this-call-fails-but-the-next-one-succeeds).

## Closing the session

`debugging-session-close` ends the session and optionally takes `conclusion_markdown` — a short writeup of what you found. **Closing auto-uninstalls every program that is still `installed` in the session.** You do not need to (and should not) manually uninstall on the way out.

The flip side: **do not close prematurely.** As soon as you close, all remaining probes stop firing. If you want events to keep accumulating while you analyze, leave the session open.

If you really need to retire one program while the session keeps running, use `debugging-session-uninstall-program` — it records a `program_uninstall` entry and is also a soft transition (the row and its events stay queryable).

## Available MCP tools

| Tool                                  | Purpose                                                                      |
| ------------------------------------- | ---------------------------------------------------------------------------- |
| `debugging-session-start`             | Open a new session with title + description                                  |
| `debugging-session-list`              | List sessions                                                                |
| `debugging-session-show`              | Fetch a session's full timeline                                              |
| `debugging-session-add-entry`         | Append `note` or `event_highlight` to the session                            |
| `debugging-session-install-program`   | Install a hogtrace program scoped to the session (records `program_install`) |
| `debugging-session-uninstall-program` | Soft-uninstall a program in the session (records `program_uninstall`)        |
| `debugging-session-program-events`    | Fetch probe-hit events for a program in the session                          |
| `debugging-session-close`             | Close the session; auto-uninstalls any still-installed programs              |

## Reference files

- [Language reference](./references/language.md) — full syntax, predicates, captures, `$req.*`, sampling, built-ins
- [Patterns](./references/patterns.md) — request duration, slow-query capture, exception tracing, conditional probes
- [Troubleshooting](./references/troubleshooting.md) — no events firing, ambiguous specifier, performance concerns
