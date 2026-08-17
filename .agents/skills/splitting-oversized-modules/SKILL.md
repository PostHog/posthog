---
name: splitting-oversized-modules
description: >
  Split an oversized Python module (a 2000+ line logic.py, models.py, api.py, or its
  test file) into a package of one module per concern, mechanically and provably
  without changing behavior. Use on any request to split / break up / decompose a god
  module or move functions out of one, and also when about to make some other change
  inside a file big enough that reading it dominates the task — splitting it first as a
  stacked base PR is usually cheaper than working around it. Covers that stacked
  workflow, measuring the payoff in read-set tokens, assigning symbols to concerns with an acyclic
  dependency graph, doing the move with AST + tokenize scripts instead of by hand,
  why never to leave a re-export shim in __init__.py, retargeting mock patch targets,
  and proving the result is a pure move. Not for extracting a shared helper into
  common/, and not for moving code between products — that is
  isolating-product-facade-contracts.
---

# Splitting oversized modules

A module nobody wants to open is a tax on every change in it. That tax is now
measurable: agents don't accumulate familiarity between tasks, so whatever must be
read to make a change gets read again on the _next_ change, and the next. A
2951-line `logic.py` beside a 3000-line `test_logic.py` means ~53k input tokens
before a line gets written, every single time.

So the goal is not tidiness. It is to make the read-set for a typical change small,
without changing what the code does. See
[references/case-study.md](references/case-study.md) for the numbers from
`visual_review`, where this recipe took the largest file from 2951 to 420 lines and
cut the read-set 81–97% per change.

## Is it worth doing here?

Worth it when the file is over roughly a thousand lines **and** it holds several
concerns that change independently **and** something is still actively changing in
it. All three matter — splitting a big, cohesive, frozen file buys nothing.

Skip it when the file is long but genuinely one concern (a single state machine, one
big query builder), or when it is generated (`api.schemas.ts`, migrations, protobuf
output), or when a wide refactor would collide with in-flight work on the same file.
Check `git log --format='%h %s' -20 -- <file>` before starting: if several people are
mid-change there, land this after them.

Do not bundle behavior changes with the move. A pure move is reviewable at a glance
once verified; a move plus "while I was in there" is neither reviewable nor
bisectable.

## Split first, then do the work you came for

The common case is not "go tidy this file" — it is arriving in an oversized module to
make some ordinary change and realising that reading it costs more than the change
does. Splitting first is then the cheaper path, and a stack is what keeps it honest:

1. Branch off master, do the split, open it as the **base** PR. Pure move, nothing else.
2. Branch your actual change off that, stacked on top.

Both diffs stay separately reviewable — the base is a mechanical move a reviewer can
check with one script, and your change reads as the small diff it really is instead of
being buried in a 6000-line reshuffle. Every later task in that module, yours included,
then reads a few hundred lines instead of a few thousand.

Keep the stack two deep and merge the base quickly. Deep stacks in this repo mean
repeated restacks, and each force-push fans out a full CI run — see the stacked-PR
guidance in AGENTS.md.

Say what you're doing before you start, in one line: which file, what it costs to read
now, and that the split lands separately. Nobody minds the base PR; they mind finding
it unannounced inside a feature diff.

## Method

### 1. Measure first, so the payoff is a number

```sh
uv run --no-project --with tiktoken python scripts/read_set.py <module> <its test file>
```

Then pick three or four representative changes across different concerns ("add a
field to X", "change how Y is posted") and write down which files each one would
need afterwards. A split helps unevenly; the spread is the honest result. Do not
measure only the change that motivated the work.

### 2. Map the symbols, and assign them to concerns

```sh
uv run --no-project python scripts/map_symbols.py <module>              # line-range table
uv run --no-project python scripts/map_symbols.py <module> --skeleton > layout.json
```

Edit `layout.json`, moving symbols into modules named after concerns. Name modules
after what they _are_ (`baselines`, `quarantine`, `ci_status`), not after layers
(`helpers`, `utils`, `core`) — a symbol whose home is obvious from the concern name
is a symbol an agent can find without reading anything else.

Two rules while assigning:

**Make the dependency graph acyclic.** Sketch which module needs which. If two
modules need each other, the split is usually along the wrong seam. Separating
_reads from writes_ fixes most cycles: in `visual_review`, `runs` (lifecycle) and
`uploads` (verification) each needed the other's run lookups, so the lookups became
a third leaf module, `run_queries`, that both depend on and neither imports back.

**Do not name a module after a common local variable.** A module called `snapshots`
or `runs` gets shadowed by `snapshots = [...]` inside a function, which works right
up until someone adds a `snapshots.foo()` call after that assignment and gets
`UnboundLocalError`. Either pick a name that won't collide, or split finer so the
name is specific (`thumbnails`, `history`, `toleration` instead of one `snapshots`).

### 3. Move the code with a script, not by hand

```sh
uv run --no-project python scripts/split_module.py <module> layout.json \
    --package-doc "Business logic for foo."
ruff check <package>/ --fix
uv run --no-project python scripts/cleanup_after_lint.py <package>
ruff check <package>/ --fix && ruff format <package>/     # again: TYPE_CHECKING is now unused
```

Hand-editing a 3000-line move loses code and silently rewrites it. `split_module.py`
copies each symbol verbatim by AST line range, refuses to run unless the layout
covers every symbol exactly once, gives each new module the original import header
for `ruff --fix` to prune, and deepens relative imports (`from .models` becomes
`from ..models`) since the modules now sit one level lower.

It requalifies cross-module references with `tokenize`, not regex. This matters:
regex also rewrites the same word inside docstrings, comments, and string literals,
so prose mentioning a function name gets mangled. `tokenize` only sees real
identifiers.

Cross-module calls come out as `from . import run_queries` plus
`run_queries.get_run(...)`, never `from .run_queries import get_run`. Module-object
imports keep one binding per symbol (so a mock patch on the definition reaches every
caller) and tolerate an accidental cycle, because `from . import x` falls back to
`sys.modules` for a partially-initialized package.

Module state every module needs its own copy of — a `logger`, a compiled regex — goes
under a `"__shared__"` key in the layout rather than being owned by one module. It gets
copied into each module that references it. Assigning it to a single module instead
would force every sibling to import that module just to log.

`cleanup_after_lint.py` then handles what `ruff --fix` can't: it deletes the
`if TYPE_CHECKING: pass` blocks ruff empties but leaves behind, and reports the
`# --- Section ---` dividers that were navigation inside the monolith (reported, not
deleted — whether a divider still earns its place is a judgment call). `ruff --fix`
runs once more after it, because removing those blocks orphans their
`from typing import TYPE_CHECKING`.

### 4. No re-export shim in `__init__.py`

The tempting shortcut is an `__init__.py` that re-exports everything, so no caller
changes and the diff stays small. Don't.

A re-export gives every symbol two bindings — `logic.get_run` and
`logic.runs.get_run` — pointing at one function. Patching either one does not affect
the other, so `patch("...logic.get_run")` silently stops intercepting internal
callers: the patch applies, the test passes, and the real implementation ran. That
failure is invisible. It also erases the benefit, since a symbol reachable from the
package root tells a reader nothing about where it lives.

Callers should import the submodule they depend on. In a facade, `run_queries.get_run(...)`
next to `approvals.finalize_run(...)` states which concern each call belongs to —
information `logic.` prefixes threw away.

### 5. Retarget callers and mock patch targets

Every `logic.foo()` becomes `<module>.foo()`, and every patch target moves to the
module that _defines_ the symbol, since that is the binding its callers resolve.
Both forms need updating:

```python
patch("products.foo.backend.logic._post_commit_status")     # -> ...logic.ci_status._post_commit_status
patch.object(logic, "_post_commit_status")                  # -> patch.object(ci_status, "_post_commit_status")
```

Then check them all resolve, which takes seconds and needs no database:

```sh
PYTHONPATH=. .flox/cache/venv/bin/python scripts/verify_patch_targets.py \
    products/foo/backend/tests --prefix products.foo
```

A _stale_ target raises at test time, so tests catch it. A _misdirected_ one —
patched on a module that no longer calls the function — applies cleanly and
intercepts nothing, so the test exercises the real implementation and may still
pass. Only this check finds that class of breakage.

Sweep `conftest.py` along with the test files. Fixtures patch too, and a rewrite pass
matched on `test_*.py` leaves conftest pointing at paths that no longer exist.

Names the old module merely re-exported (`WRITER_DB`, a model, `transaction`) should
now come from their real source rather than being re-exported again by the package.

### 6. Split the tests the same way, mirroring the package

A split source file beside an untouched 3000-line test file only solves half the
problem — adding a test still costs the full read. Mirror the package:
`logic/comments.py` ↔ `tests/logic/test_comments.py`. Assign whole test classes; do
not carve up a class, which stops being a pure move.

The mirror is also why the test files need no prefix: `tests/logic/test_runs.py`
cannot collide with an existing `tests/test_runs.py`, and there is exactly one
obvious place to look for a module's tests.

### 7. Prove it is a pure move

```sh
git show HEAD:products/foo/backend/logic.py > /tmp/before.py
uv run --no-project python scripts/verify_pure_move.py /tmp/before.py products/foo/backend/logic

git show HEAD:products/foo/backend/tests/test_logic.py > /tmp/before_tests.py
uv run --no-project python scripts/verify_pure_move.py /tmp/before_tests.py \
    products/foo/backend/tests/logic --strip-package products/foo/backend/logic
```

This compares every top-level definition before and after, ignoring the module
qualification the split introduced, and reports anything missing, unexpected,
duplicated with drift, or actually changed. It is what makes a "48 files changed"
diff reviewable: _every definition is identical modulo qualification_ is a claim a
reviewer can check, unlike a diff that large.

Run it again after any cleanup pass, and never compare against your own transformed
output — always re-derive the "before" from git.

### 8. Then the test suite

Static checks cover import wiring, patch targets, and equivalence, but run the suite
before claiming it works. Confirm each new module imports standalone too, since
import order can hide a cycle:

```sh
hogli test products/foo/backend/tests
```

## Left for you

- Decide on the `# --- Section ---` dividers `cleanup_after_lint.py` reports.
- Rename locals that shadow a new module name — `ruff` catches the reachable ones, not
  a local assigned before any module use.
- Update any doc or skill that links the old path. A split leaves dead links behind
  (`products/architecture.md` and `isolating-product-facade-contracts` both pointed at
  `visual_review/backend/logic.py`).

## References

- [references/case-study.md](references/case-study.md) — the `visual_review` split:
  layout, measured read-set savings, and what the scripts caught
- [references/gotchas.md](references/gotchas.md) — the traps in full, each with the
  symptom you'd actually see
