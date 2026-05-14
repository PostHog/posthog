# Common hogtrace patterns

Reach for these shapes first when starting a new program. Adapt the dotted paths and capture names to the user's codebase; the structure is the part worth reusing.

## Capture only failure cases

When the question is "what does this function look like when it breaks?":

```dtrace
fn:myapp.payments.process_payment:exit
/ exception != None /
{
    capture(
        args=args,
        exception=exception,
        user_id=$req.user_id
    );
}
```

The predicate gates on `exception != None`, so successful calls are zero overhead beyond the predicate evaluation.

## Capture return values for a specific input

When the question is "what does this return when called with X?":

```dtrace
fn:myapp.users.lookup_user:exit
/ arg0 == "marce@dziban.net" /
{
    capture(input=arg0, result=retval);
}
```

Tight predicates make this safe to run on hot paths without sampling.

## Measure duration across entry and exit

The canonical use of `$req.*` — start time on entry, diff on exit:

```dtrace
fn:myapp.api.search:entry
{
    $req.search_start = timestamp();
    $req.search_query = arg0;
}

fn:myapp.api.search:exit
{
    capture(
        query=$req.search_query,
        duration=timestamp() - $req.search_start,
        result_count=len(retval),
        had_error=exception != None
    );
}
```

The entry probe sets state; the exit probe captures the delta and any other useful state. No event is emitted on entry — entries here only seed the request store.

## Slow-only query capture

Trace database calls but only when they're slow:

```dtrace
fn:myapp.db.execute_query:entry
{
    $req.query_start = timestamp();
    $req.query_sql = arg0;
}

fn:myapp.db.execute_query:exit
/ (timestamp() - $req.query_start) > 0.5 /
{
    capture(
        sql=$req.query_sql,
        duration=timestamp() - $req.query_start,
        request_id=$req.request_id
    );
}
```

The threshold (`0.5` seconds here) is in the exit predicate, so fast queries cost only the timestamp diff plus a comparison.

## Sample a high-traffic probe

When you need a representative slice of a busy function:

```dtrace
fn:myapp.api.list_products:entry
/ rand() < 0.01 /
{
    capture(args=args, kwargs=kwargs);
}
```

`rand() < 0.01` is roughly 1%. For 0.1%, use `0.001`. Combine with other predicates with `&&`:

```dtrace
/ rand() < 0.1 && arg0.region == "eu" /
```

## Trace a whole request

Identify the request, then thread its id through every probe:

```dtrace
fn:django.core.handlers.wsgi.WSGIHandler:entry
{
    $req.request_id = arg0.META["REQUEST_ID"];
    $req.request_start = timestamp();
    $req.user_id = arg0.user.id;
}

fn:myapp.db.execute_query:entry
/ $req.request_id != None /
{
    capture(request_id=$req.request_id, sql=arg0);
}

fn:myapp.cache.get:exit
/ $req.request_id != None /
{
    capture(request_id=$req.request_id, key=arg0, hit=retval != None);
}

fn:django.core.handlers.wsgi.WSGIHandler:exit
{
    capture(
        request_id=$req.request_id,
        user_id=$req.user_id,
        duration=timestamp() - $req.request_start,
        status=retval.status_code
    );
}
```

In PostHog, join events on `properties.request_id` to reconstruct the full timeline.

## Cross-call diff — "this call fails but the next one succeeds"

The single most powerful debugging pattern for bugs gated on hidden state (cache counters, per-request flags, retry-state machines, throttle windows). Capture the **same named locals at `:exit`** for every call to the suspect function, then visually diff two consecutive events.

```dtrace
fn:myapp.payments.charge_card:exit
{
    capture(
        retry_count=locals["_retry_count"],
        signing_secret=locals["signing_secret"],
        is_idempotent=locals["_is_idempotent"],
        retval=retval,
        exception=exception
    );
}
```

Reproduce the bug (fail → succeed, or any A → B sequence). Pull events for the program — the two most recent `:exit` rows are your A and B. Lay them side by side:

| field            | call A (fails) | call B (succeeds) |
| ---------------- | -------------- | ----------------- |
| `retry_count`    | `0`            | `1`               |
| `signing_secret` | `"sec-Y"`      | `"sec-X"`         |
| `is_idempotent`  | `True`         | `False`           |

Any column where A and B differ is a candidate cause. This works because you don't need to know in advance which local is the culprit — capture them all, then look at the diff.

Reach for this pattern whenever the user describes the bug as "first time fails, second works" or "fails then retries through." Don't try to read the source to figure out which local matters — capture all locals at `:exit` and let the diff tell you. The locals named with `_underscore_prefix` are usually the most interesting (they're typically derived flags the function computed internally).

## Exploratory: "I don't know what to look at yet"

Capture everything on a low-traffic function for the first call to learn the shape:

```dtrace
fn:myapp.background.weekly_report:entry
{
    capture(args=args, kwargs=kwargs);
}

fn:myapp.background.weekly_report:exit
{
    capture(retval=retval, exception=exception);
}
```

Once you've seen one or two events, replace this with named-capture probes that target the specific fields you care about.

## Confirm a probe is firing at all

When you suspect the probe specifier doesn't resolve, install a no-op-style probe first:

```dtrace
fn:myapp.module.suspect_function:entry
{
    capture(fired=1);
}
```

If you see events, the path resolves and the function is being called. If not, the path is wrong (or the function genuinely isn't running). Once confirmed, replace with the real probe.

## Anti-patterns

- **Unguarded wildcards on hot paths**: `fn:myapp.*:entry` with no sampling will firehose events.
- **`capture(locals)` left in production**: useful for one-shot exploration, but `locals` can include large objects that bloat the event payload.
- **Stateful tricks across requests**: `$req.*` is per-request, not global. There is no global mutable state available to probes.
- **Forgetting to uninstall**: probes you "left running while debugging" accumulate. List periodically.
