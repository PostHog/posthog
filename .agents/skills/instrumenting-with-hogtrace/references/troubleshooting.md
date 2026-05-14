# Troubleshooting hogtrace programs

When a program is installed but events aren't showing up — or showing up in unexpected shape — work through these in order.

## "I installed the program and there are no events"

**1. Did you wait long enough?**

The runtime polls PostHog roughly every 30 seconds. After install, expect up to a minute before the program is picked up, _plus_ however long until the target function gets called. For low-traffic targets, give it a few minutes.

**2. Does the specifier resolve in the running process?**

The runtime walks the dotted path downward — `myapp.users.UserService.create` is tried as a module first, then as `myapp.users.UserService` with attribute `create`, etc. If nothing resolves, the probe is silently skipped.

Re-read the program (`live-debugger-programs-show`) and verify the path corresponds to a _callable importable from the application_. Common gotchas:

- The function exists but lives in a sub-module the application never imports until a specific code path runs. The probe won't be installed until that import happens.
- The path points to a class instance attribute set at runtime, not a class-level method. Probes only work against statically-resolvable callables.
- The path points to a closure or lambda. Not instrumentable.
- The function is decorated with something that replaces it with a non-Python wrapper (C extension, Cython). Not instrumentable.
- The path is one segment too long (e.g., includes the class instance name).

To confirm the path, switch to a no-op probe that captures something trivial (`capture(fired=1)`) — see [patterns](./patterns.md#confirm-a-probe-is-firing-at-all). If that emits events, the path works.

**3. Is the function actually being called in the window you're watching?**

Try a function you know is hot (e.g., a request handler) as a sanity check.

**4. Is the predicate always false?**

Re-install without the predicate temporarily. If events start firing, the predicate is the culprit. Common causes:

- Comparing a `$req.*` value that was never set (reads return `None`).
- Comparing strings with the wrong type (e.g., `arg0 == 42` when `arg0` is `"42"`).
- Compound conditions where one branch is `None`, making the whole expression coerce to false.

## "My program rejected at install time"

The install endpoint compiles the source. Syntax errors are reported back. Common ones:

- Missing trailing `;` on a statement inside `{ ... }`.
- Unbalanced braces or `/`.
- Using Python-only operators (`is`, `is not`, `and`, `or`) instead of hogtrace's (`==`, `!=`, `&&`, `||`).
- Calling a function that isn't a built-in. The only callables in probe bodies are `capture` / `send`, `timestamp`, `rand`, `len`, `str`, `int`, `float`.

If the install endpoint accepted the source but events never arrive, syntax is not the problem — see "no events" above.

## "Events are firing but the fields I want are missing"

Open one of the event objects (`live-debugger-programs-events`) and look at `locals`. Named captures (`capture(foo=arg0.bar)`) appear as keys in `locals`. Positional captures (`capture(arg0)`) appear under their positional name.

If a captured expression raised at probe time (e.g., `arg0.user.email` when `arg0.user` was `None`), the field may be missing or null. Add a predicate that guards the access:

```dtrace
/ arg0.user != None /
{ capture(email=arg0.user.email); }
```

## "Too many events / runaway capture"

If you accidentally installed a wildcard probe on a hot path without sampling:

1. **Uninstall immediately** via `live-debugger-programs-uninstall`. Don't try to "edit it down" — there's no in-place update. Uninstall first, then install a tighter version.
2. The events already emitted stay in PostHog. They're not destructive, but they'll affect anything that aggregates over `$data_breakpoint_hit` events.

For high-traffic targets, default to sampling at install time. `/ rand() < 0.01 /` for ~1%, `/ rand() < 0.001 /` for ~0.1%.

## "I want to update a program without losing event history"

You can't update in place. Uninstall the old program (its row stays, status moves to `uninstalled`) and install a new one with the new source. The new program gets a new id; the old one's events remain queryable by their original id.

If you need history across versions, include a version marker in the program's `description` (e.g., "v2: narrower predicate, after 1% sampling proved insufficient") so the list view is self-explanatory.

## "How do I see what's currently installed?"

`live-debugger-programs-list` returns all programs, most recently installed first. Each entry has `id`, `description`, `status` (`installed` or `uninstalled`), and timestamps. Source code is omitted from the list — use `live-debugger-programs-show` for full source.

To check just what's currently active: filter to `status == "installed"` mentally and inspect any that look stale.

## "Performance — should I worry about probe overhead?"

Each probe call goes through a Rust VM with bounded execution time. The cost per hit is microseconds _if the predicate filters early_. The two things that turn cheap into expensive:

- Capturing large objects (`capture(locals)` when a local is a 10MB DataFrame).
- Probes on extremely hot inner loops without sampling.

If you suspect probe overhead, uninstall the program; baseline latency should return immediately. The wrapper itself stays on the function until the next call resolves the empty probe set and self-cleans, so a single slow next call may still show the wrapper before the runtime drops it.
