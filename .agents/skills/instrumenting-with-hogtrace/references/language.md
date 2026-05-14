# Hogtrace language reference

A minimal reference for writing hogtrace programs to install via the live debugger. The full upstream spec lives in the hogtrace repo (`hogtrace/docs/SPEC.md`); this file is the working subset you need to get probes right on first install.

## Probe structure

```dtrace
provider:dotted.path:probe_point
/ predicate /                   # optional
{
    action;
    action;
}
```

- `provider` — `fn` is the only one today.
- `dotted.path` — fully-qualified Python path: `module.function`, `module.Class.method`, `module.submodule.cls.method`. Wildcards (`*`) allowed for one segment.
- `probe_point` — `entry` or `exit`. (Line offsets like `entry+5` exist but are niche; prefer `entry`/`exit` unless you genuinely need a bytecode offset.)

Programs can contain multiple probes — they share constants and request-scoped state.

## Variables available in the body

### Entry probes

- `args` — tuple of positional arguments
- `arg0`, `arg1`, … — individual positional arguments
- `kwargs` — dict of keyword arguments
- `self` — receiver for method calls
- `locals` — dict of local variables (only useful for `entry+N` style probes)

### Exit probes

- Everything from entry, plus:
- `retval` — the function's return value
- `exception` — the exception object if it threw, otherwise `None`

### Anywhere

- `$req.<name>` (alias `$request.<name>`) — request-scoped variable. Reads return `None` if unset.

## Predicates

A predicate is a boolean expression between `/ ... /`. The probe body only runs if the predicate evaluates truthy.

```dtrace
fn:myapp.auth.check:entry
/ arg0 == "admin" /
{ capture(args); }
```

Compose with `&&` and `||`. A non-boolean result is treated as false. Predicates can call `len(...)`, `rand()`, `timestamp()`.

Use predicates for:

- Filtering to interesting cases (`arg0.role == "admin"`)
- Failure-only capture (`exception != None`)
- Sampling (`rand() < 0.01`)
- Cross-probe gating (`$req.user_id != None`)

## Captures

`capture(...)` is how data leaves the probe and arrives as an event in PostHog.

```dtrace
capture(args)                                 # positional: emits a "args" property
capture(retval, exception)                    # multiple positional
capture(user_id=arg0, email=arg1.email)       # named — preferred
capture(name="admin_create", details=args)    # named with literals
capture(locals)                               # everything (exploratory only)
```

**Prefer named captures.** Positional captures become opaque blob fields in the event; named captures become first-class properties you can query in HogQL.

`send(...)` is an alias for `capture(...)`. Use `capture` for consistency with PostHog terminology.

## Request-scoped variables (`$req.*`)

Variables that persist across probes within a single request:

```dtrace
fn:django.core.handlers.wsgi.WSGIHandler:entry
{
    $req.request_id = arg0.META["REQUEST_ID"];
    $req.start_time = timestamp();
}

fn:myapp.db.execute_query:entry
/ $req.request_id != None /
{
    capture(request_id=$req.request_id, sql=arg0);
}

fn:django.core.handlers.wsgi.WSGIHandler:exit
{
    capture(
        request_id=$req.request_id,
        duration=timestamp() - $req.start_time,
        status=retval.status_code
    );
}
```

Notes:

- Storage is thread-local to the request context and cleared when the request ends.
- Reading an unset variable returns `None` — guard with `/ $req.foo != None /` if downstream logic needs the value.
- Cannot be used to communicate between requests. For cross-request state, capture and aggregate in PostHog.

## Sampling

For high-traffic probes, do not capture every hit.

**Predicate form (recommended — composes with other conditions):**

```dtrace
fn:myapp.api.list_products:entry
/ rand() < 0.01 /
{ capture(args); }
```

**Directive form (simpler when there's no other predicate):**

```dtrace
fn:myapp.api.list_products:entry
{
    sample 1%;
    capture(args);
}
```

Both `sample 10%` and `sample 1/100` work. The directive runs before the rest of the body — if the sample check fails, the body short-circuits.

## Data access

```dtrace
arg0.attribute                  # attribute on Python object
arg0["key"]                     # dict lookup
arg0[0]                         # list/tuple indexing
arg0.user["email"]              # chained: attribute then dict
retval.data[0]["id"]            # arbitrary depth allowed
```

Comparisons preserve Python semantics:

```dtrace
/ arg0.count > 100 /            # numeric
/ arg0.name == "admin" /        # string
/ arg0.enabled /                # truthiness
/ retval["status"] != "ok" /    # dict access in comparison
```

## Built-in functions

| Function                     | Returns                                               |
| ---------------------------- | ----------------------------------------------------- |
| `timestamp()`                | Current Unix timestamp as float (seconds since epoch) |
| `rand()`                     | Random float in `[0.0, 1.0)`                          |
| `len(obj)`                   | Length of list/dict/string/tuple                      |
| `str(obj)`                   | String coercion                                       |
| `int(obj)`                   | Integer coercion                                      |
| `float(obj)`                 | Float coercion                                        |
| `capture(...)` / `send(...)` | Emit captured data as a PostHog event                 |

You cannot call arbitrary application code — only the built-ins listed. This is a deliberate sandboxing boundary: no `eval`, no filesystem, no network.

## Wildcards

A single `*` is allowed per dotted segment:

```dtrace
fn:myapp.api.*:entry            # every function in the myapp.api module
fn:myapp.*.create_*:entry       # cross-module + cross-name matching
```

Wildcards multiply traffic — combine with sampling. A wildcard probe on a hot module without sampling is the fastest way to flood the project with events.

## What you cannot do

- Modify variables of the instrumented function (probes are read-only against the frame).
- Call functions other than the built-ins listed above.
- Access the filesystem or network from inside a probe.
- Define your own functions.
- Loop or branch in the probe body (only sequential statements).
- Reference globals from the application (use `$req.*` to thread state between probes).
- Update an installed program in place — uninstall and re-install with new source.
