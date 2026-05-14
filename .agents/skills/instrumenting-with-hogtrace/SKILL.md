---
name: instrumenting-with-hogtrace
description: Use when the user asks to observe runtime behavior of a running Python service via hogtrace probes — installing, listing, inspecting, or uninstalling live debugger programs through the PostHog MCP. Covers writing hogtrace source (probes, predicates, captures, request-scoped variables, sampling), choosing probe points safely, installing programs, and querying the events they emit. Trigger on phrases like "install a hogtrace program", "add a probe to function X", "live debug this code", "see what arguments / locals / return value this function gets in prod", "trace requests through Y", or any mention of hogtrace, live debugger, runtime instrumentation, or DTrace-style probes for a PostHog-instrumented Python service.
---

# Instrumenting a Python service with hogtrace

Hogtrace is a DTrace-inspired probe language. You write small declarative programs that say "when function X is entered/exited, capture these values." The PostHog libdebugger runtime polls the project, installs your program, and the probes start emitting events the moment they fire. This skill is the workflow for going from "I want to understand what happens at line Y" to "events are flowing into PostHog."

You always operate through the live debugger MCP tools — never edit application code, never restart the service. Programs go in, events come out, programs come back out when you're done.

## The job to be done

```text
1. Understand the question         (what does the user actually want to see?)
2. Pick probe points               (which functions, entry or exit, where to capture)
3. Write the hogtrace source       (predicates, captures, $req.* if cross-probe)
4. Install via MCP                 (live-debugger-programs-install)
5. Wait for events                 (libdebugger polls every ~30 seconds)
6. Inspect events                  (live-debugger-programs-events)
7. Iterate                         (refine specifier, add predicates, sample)
8. Uninstall                       (live-debugger-programs-uninstall)
```

Treat each install as an experiment: small, targeted, time-boxed. Broad wildcards on hot paths can pour data into PostHog — sample aggressively when in doubt (see [language reference](./references/language.md#sampling)).

## Probe-point fundamentals

A probe specifier is `provider:dotted.path:probe_point`. Today only the `fn` provider is supported.

```dtrace
fn:myapp.users.create_user:entry
fn:myapp.users.UserService.create:exit
fn:myapp.api.*:entry                  # wildcards allowed
```

The dotted path must resolve to a **callable importable in the target process**. The runtime walks prefixes downward — `myapp.users.UserService.create` is tried first as a module, then as `myapp.users.UserService` with attribute `create`, then `myapp.users` with attributes `UserService.create`, and so on. If nothing resolves, the probe is silently skipped and you get no events.

What the runtime **cannot** instrument:

- Lambdas
- Closures captured at runtime
- Instance attributes that hold functions assigned dynamically
- Builtins, C extensions, things not reachable from a Python module

When the user names a "function," confirm the import path before composing the probe. Wrong path = no events, and you'll waste an iteration cycle waiting on the next poll.

## Choosing entry vs exit

| You want to see…                             | Use                                              |
| -------------------------------------------- | ------------------------------------------------ |
| Arguments being passed in                    | `:entry`                                         |
| Return value or whether it threw             | `:exit`                                          |
| Duration (start time on entry, diff on exit) | Both, joined via `$req.*`                        |
| State midway through                         | `:entry+N` (bytecode offset — niche, often skip) |

Exit probes get `retval` and `exception` (None if the function returned normally). If the user asks "what did this return when it failed," that's `:exit` with predicate `/ exception != None /` capturing `args` and `exception`.

## Writing the source

Keep it small. A typical first program is one or two probes:

```dtrace
fn:myapp.payments.process_payment:exit
/ exception != None /
{
    capture(args=args, exception=exception, user_id=$req.user_id);
}
```

Always use **named captures** (`capture(name=value, ...)`) when you can — they show up as distinct properties on the event and are far easier to read in PostHog than positional captures. Reserve `capture(args)` and `capture(locals)` for "I don't know what I'm looking for yet" exploration; once you know, name the fields.

Predicates filter at runtime cheaply — push as much filtering into them as possible rather than capturing everything and filtering after. Predicates can read `args`, `arg0..argN`, `kwargs`, `self`, `retval`, `exception`, and `$req.*`, plus call `len(...)`, `rand()`, `timestamp()`. A non-boolean predicate result is treated as false.

For high-traffic targets, sample. Either `/ rand() < 0.01 /` in the predicate (recommended — composable) or `sample 1/100;` as the first statement in the body. See [language reference](./references/language.md) for full syntax.

When you need to correlate state across multiple probes in the same request (e.g., start time on entry, duration on exit), use request-scoped variables (`$req.*`). They're thread-locally scoped to the request and cleared when the request finishes. Reading an unset `$req.*` returns `None` rather than failing.

For common shapes — request duration tracking, slow-query capture, exception capture, conditional traces — see [patterns](./references/patterns.md). Start there for any non-trivial probe.

## Installing the program

Use `live-debugger-programs-install` with:

- `code`: the hogtrace source string. Multi-line is fine.
- `description`: a short human-readable explanation of what you're observing and why. This is what appears in the program list — make it specific. "Trace failed payments to see exception types we're missing" beats "payment probe."

The tool returns the program's `id`. Save it — you need it for events and uninstall.

The runtime poller picks up the program on its next tick (~30 seconds). Probes start firing as soon as the wrapper is installed on the target function. There's no "deploy" step — installation is the deploy.

**Arming is per-worker and asymmetric.** The runtime manager runs in each Granian worker process independently; each worker polls on its own ~30s cycle. After install, expect probes to appear on different workers at different times within the first minute — a request that lands on a not-yet-armed worker will silently bypass the probe. Plan to wait **at least 60 seconds** after install before assuming the probe is wired up; for low-traffic targets give it longer.

## Watching for events

`live-debugger-programs-events` returns the most recent probe-hit events for one program (by `id`), most recent first. Each event has:

- `timestamp` — when the probe fired
- `probe_id` — which probe in the program (relevant when a program has multiple)
- `filename`, `line_number`, `function_name` — source location at hit
- `locals` — captured local variables (whatever you named in `capture(...)`)
- `stack_trace` — the call stack at the hit site

**Important**: if you just installed and see no events, wait at least 60 seconds and retry. The poll cycle is ~30s and the program needs to be installed _and_ the function needs to be called _after_ installation.

If after a couple of minutes you still see nothing:

1. Re-read the program with `live-debugger-programs-show` and check the source compiled at install time (it would have rejected obvious syntax errors). The probe target may not resolve in the running process — confirm the dotted path.
2. The function may genuinely not be called in this window. Lower-traffic functions need patience.
3. The predicate may always evaluate false — try the same probe without the predicate to confirm probes ARE firing.

See [troubleshooting](./references/troubleshooting.md) for more.

## Iterating

Hogtrace programs are immutable after install (no update endpoint). To change a program, uninstall the old one and install a new one. The old program's events stay queryable for history; only its probes stop firing.

When iterating quickly, install with a description that includes a version marker ("v2: narrower predicate") so the program list stays scannable.

**Prefer adding probes to a single broad program over many install/uninstall cycles.** Each uninstall→install round costs another full ~60s window for workers to drop the old patches and pick up the new ones, and rapid churn can leave some workers in a stale state where the new program appears silent. If you can predict which captures you'll want before installing, install them all in one program from the start.

## Updating program in-place is not supported — but here's the iteration loop

Because programs are immutable, every change is uninstall + install. To avoid burning iterations:

1. Before installing, decide what you want at `:exit` (usually named locals) and capture them all in one shot — you'll thank yourself when the same data answers your follow-up question.
2. If a probe seems silent after install, **don't immediately reinstall**. First, give it 60–90s. Then verify attachment with a `capture(fired=1)` sanity probe rather than tweaking the original.
3. When the user describes a bug as "X happens the first time but not the second," reach for the cross-call diff pattern in [patterns.md](./references/patterns.md#cross-call-diff--this-call-fails-but-the-next-one-succeeds) — capture named locals at `:exit` and diff two consecutive events.

## Cleaning up

When you're done observing, **uninstall**. Don't leave probes running indefinitely — they cost a tiny amount per call on the hot path, and noise piles up in PostHog. Use `live-debugger-programs-uninstall` with the program `id`. Uninstall is a soft transition (status becomes `uninstalled`); the row and its events stay queryable.

If you're not sure what's currently installed, `live-debugger-programs-list` returns everything with status, most recently installed first. Filter to `installed` mentally; show full source for any you want to inspect with `live-debugger-programs-show`.

## Available MCP tools

| Tool                               | Purpose                                        |
| ---------------------------------- | ---------------------------------------------- |
| `live-debugger-programs-install`   | Install a hogtrace program (writes to project) |
| `live-debugger-programs-list`      | List all programs (code omitted)               |
| `live-debugger-programs-show`      | Retrieve one program with full source          |
| `live-debugger-programs-events`    | Query probe-hit events for a program           |
| `live-debugger-programs-uninstall` | Soft-uninstall a program by id                 |

Install/uninstall require `live_debugger:write`. List/show/events require `live_debugger:read`.

## Reference files

- [Language reference](./references/language.md) — full syntax, predicates, captures, `$req.*`, sampling, built-ins
- [Patterns](./references/patterns.md) — request duration, slow-query capture, exception tracing, conditional probes
- [Troubleshooting](./references/troubleshooting.md) — no events firing, ambiguous specifier, performance concerns
