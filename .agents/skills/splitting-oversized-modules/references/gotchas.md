# Gotchas, with the symptom each one produces

Ordered by how expensive they are to find late.

## A re-export shim breaks mocks silently

`logic/__init__.py` re-exporting everything gives each symbol two bindings that point
at one function. Patching one does not affect the other.

**Symptom:** `patch("products.foo.backend.logic.write_artifact_bytes")` applies with
no error, the assertion on the mock fails ("expected 1 call, got 0") — or worse, the
test never asserts on the mock and just quietly runs the real implementation, hitting
real storage. Nothing points at the shim.

**Fix:** no re-exports. Callers import the submodule; there is one binding per symbol.

## A module named like a variable becomes an UnboundLocalError

```python
from .logic import runs

def list_runs(...):
    runs = run_queries.list_runs_for_team(...)   # shadows the module for this whole scope
    return [_to_run(r) for r in runs]            # fine today
```

**Symptom:** nothing, until someone adds `runs.create_run(...)` later in that
function and gets `UnboundLocalError: cannot access local variable 'runs'`. Python
binds the whole scope, so even a call _above_ the assignment fails.

**Detection:** `ruff check --select F` flags the reachable cases (`F811`, `F823`), but
not one where the local is assigned before any module use. Grep for assignments
matching your module names, or avoid plural nouns that read like collections.

## Regex requalification corrupts prose

Rewriting `\bget_run\b` → `run_queries.get_run` also hits docstrings, comments, and
string literals that mention `get_run`.

**Symptom:** docstrings reading "see `run_queries.get_run` for the merge-base logic"
where the original said `_get_merge_base_sha`, and log event names or SQL fragments
mangled inside string literals.

**Fix:** `tokenize`, rewriting `NAME` tokens only, skipping any preceded by `.`,
`def`, or `class`.

## `from .mod import func` re-creates the two-binding problem

Inside the package, importing symbols instead of modules gives each importer its own
binding — the same mock-patch trap as the shim, one level down, plus real
`ImportError` risk if any cycle survives.

**Fix:** `from . import mod` and call `mod.func()`. This also survives an accidental
cycle: since Python 3.7, `from . import mod` falls back to `sys.modules` when the
package attribute isn't set yet.

## Relative imports break one level down

Moving `logic.py` to `logic/runs.py` invalidates every `from .models import ...`.

**Symptom:** `ModuleNotFoundError: No module named 'products.foo.backend.logic.models'`
at import time. Loud and immediate.

**Fix:** deepen one level (`from ..models`). `split_module.py` does this; watch for
imports _inside_ functions, which the same rule covers but which are easy to miss by
hand.

## Symbol-import callers outside the package

`from ..logic import HashIntegrityError` (a symbol, not a module) is invisible to a
script that only rewrites `from X import logic`.

**Symptom:** `ImportError: cannot import name 'HashIntegrityError' from
'products.foo.backend.logic'` at collection time.

**Detection:** after splitting, grep for imports from the package that name something
other than a module.

## Module state past the header boundary gets dropped

A header sliced as "everything up to the last statement that binds no name" stops
before `logger = structlog.get_logger(__name__)`.

**Symptom:** `ruff check --select F821` reports `Undefined name 'logger'` in each
module that logs. Caught statically, but only if you lint before running anything.

## Reads and writes needing each other is a cycle, not a dead end

Lifecycle code calls verification code, verification code needs the same lookups.

**Fix:** pull the read-only queries into a leaf module both depend on. This is a
better design than the cycle-breaking hack it replaces, and it is usually where the
seam wanted to be.

## An AST-equivalence check with an asymmetric normalizer lies

A `NodeTransformer` that rewrites `mod.attr` → `attr` is order-sensitive on nested
attributes and treats a bare module name argument (`patch.object(ci_status, "x")`)
differently from an attribute access.

**Symptom:** the verifier reports classes as changed while a textual diff of the same
classes shows nothing — as happened here, with the reported set shifting each time
the normalizer was adjusted.

**Fix:** canonicalize textually on the unparsed form (strip `<module>.` prefixes,
collapse bare module names), which is symmetric by construction. And derive "before"
from `git show`, never from your own earlier output.

## conftest.py patches too

A retarget sweep matched on `test_*.py` misses `conftest.py`, and fixtures patch just
like tests do.

**Symptom:** a fixture that is supposed to stub an integration stops stubbing it, so
tests in whole classes fail on assertions about mocked side effects (or worse, reach
the real dependency). The failures look unrelated to the split.

**Detection:** `verify_patch_targets.py` covers `conftest.py`. Include it in every
sweep and every check.

## A slow or busy test database is not a reason to skip verification

The shared `test_posthog` can be mid-migration from another branch, or in use by a
parallel session that a `--create-db` would break.

**Symptom:** every test errors identically — `database "test_posthog" already exists`
followed by `is being accessed by other users`, or a migration replaying a column that
is already there. Check `pg_stat_activity` for the other session and
`pgrep -f pytest` for the other worktree before concluding anything about your change.
Do not drop a database another session is using; wait for it, or queue your run behind
it.

Static verification covers most of the risk without a database: definition
equivalence, standalone imports of every module (in both directions, since import
order hides cycles), patch-target resolution, `ruff`, and the type checker. Run the
suite before claiming it passes, but do not let a busy database stall the work — and
do not drop a database another session is using.

Note that `PYTEST_XDIST_WORKER` gives per-worker Postgres databases, but products
with their own databases may not get theirs created on that path — the symptom is
every test erroring on `connection to server failed` for
`test_posthog_gw0_<product>`.
