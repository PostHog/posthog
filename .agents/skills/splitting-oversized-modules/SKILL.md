---
name: splitting-oversized-modules
description: >
  Split an oversized Python module (a thousand-plus-line logic.py, models.py, api.py, or its
  test file) into a package of one module per concern, mechanically and provably without
  changing behavior. Use on a request to split / break up / decompose a god module or move
  functions out of one, once a human has agreed to split one before some other change, or
  before restructuring code inside a module already over roughly a thousand lines — breaking
  up a long function or extracting helpers in place leaves everything in the same file, so
  check the worth-it gate and propose the split first. Covers that gate, assigning symbols to
  concerns with an acyclic dependency graph, the AST plus tokenize move script, and proving
  the result is a pure move. Python only — for frontend files use writing-ui-components. Not
  for extracting a shared helper into common/, and not for moving code between products,
  which is isolating-product-facade-contracts.
---

# Splitting oversized modules

A module nobody wants to open taxes every change in it, and agents pay that tax on every
task because they do not carry knowledge between them. A 3000-line `logic.py` beside a
3000-line `test_logic.py` is roughly 55k input tokens of reading before a line gets written.
Splitting one measured case cut the read-set 81 to 97% depending on the concern touched,
while total lines grew about 5% from the repeated import headers.

So the goal is a small read-set for a typical change, not tidiness.

## Is it worth doing here?

All three must hold: over roughly a thousand lines, several concerns that change
independently, and something still actively changing in it. A big cohesive frozen file buys
nothing. Skip generated files, and skip a file several people are mid-change in
(`git log --oneline -20 -- <file>`).

A complexity warning on one function is a symptom of this, not a separate job. Extracting
that function into helpers leaves every helper in the same file, so the read-set is
unchanged and the file gets longer. Measure the file first (`wc -l`), and when it clears the
gate, propose the split instead of the in-place extraction.

Splitting is a separate PR from whatever you came to do. Land the move as its own base PR
and branch your work on top — see `/stacking-prs`. Never bundle it into a feature diff, and
say what you are doing in one line before you start: which file, and that the split lands
separately. Nobody minds the base PR; they mind finding it inside a feature diff.

If a human has not asked for the split, propose it and let them decide.

## Method

Commands assume the repo root. `S=.agents/skills/splitting-oversized-modules/scripts`.

### 1. Map the symbols and assign them to concerns

```sh
uv run --no-project python $S/split_module.py <module> --skeleton > layout.json
```

Edit `layout.json` into modules named after concerns (`baselines`, `quarantine`,
`ci_status`), not layers (`helpers`, `utils`, `core`). Put module-level state every module
needs its own copy of — a logger, a compiled regex — under `"__shared__"`.

Two rules while assigning:

**Keep the dependency graph acyclic.** If two modules need each other, the seam is wrong.
Separating reads from writes fixes most cycles: a lifecycle module and a verification module
that both need the same lookups should share a third leaf module holding those lookups.

**Do not name a module after a common local variable.** A module called `artifacts` or
`runs` gets shadowed by `artifacts = [...]` inside a function, and Python binds the whole
scope, so a call _above_ the assignment fails too. `ruff` catches the reachable cases
(`F811`, `F823`) but not one where the local is assigned before any module use. Pick a
non-colliding name, or split finer until the name is specific.

### 2. Move the code

```sh
uv run --no-project python $S/split_module.py <module> layout.json
ruff check <package>/ --fix && ruff format <package>/
```

Hand-editing a 3000-line move loses code and silently rewrites it. The script copies each
symbol verbatim by AST line range, refuses to run unless the layout covers every symbol
exactly once, and requalifies cross-module references with `tokenize` so it never rewrites a
name inside a docstring or string literal.

Cross-module calls come out as `from . import baselines` plus `baselines.foo(...)`, never
`from .baselines import foo`. One binding per symbol means a mock patch on the definition
reaches every caller, and `from . import x` also survives an accidental cycle by falling
back to `sys.modules`.

`ruff --fix` leaves an emptied `if TYPE_CHECKING: pass` behind. Delete those, then re-run
`ruff check --fix` so the orphaned `TYPE_CHECKING` import goes too. The
`# --- Section ---` dividers from the monolith are usually redundant once the module name
says it: `rg -n '^#\s*-{2,}' <package>/`.

### 3. Retarget callers and mock patch targets

Every `logic.foo()` becomes `<module>.foo()`, and every patch target moves to the module
that _defines_ the symbol, since that is the binding its callers resolve:

```python
patch("products.foo.backend.logic._post_commit_status")   # -> ...logic.ci_status._post_commit_status
patch.object(logic, "_post_commit_status")                # -> patch.object(ci_status, "_post_commit_status")
```

Sweep `conftest.py` too, not just `test_*.py` — fixtures patch, and a pass matched on test
files leaves conftest pointing at paths that no longer exist. Enumerate candidates with
`rg -n 'patch\(|patch\.object\(' <tests>/`. Watch for forms a naive sweep misses: a combined
`from x import a, logic`, a symbol import (`from ..logic import SomeError`), and a name the
old module merely re-exported, which should now come from its real source.

### 4. Split the tests the same way

A split module beside an untouched 3000-line test file solves half the problem. Mirror the
package, so `logic/comments.py` pairs with `tests/logic/test_comments.py`:

```sh
uv run --no-project python $S/split_module.py <test file> tests_layout.json \
    --package-dir <tests>/logic --init-doc "Unit tests for the logic package."
```

Assign whole test classes. Carving up a class stops being a pure move.

### 5. Prove it is a pure move

```sh
git show HEAD:<module> > /tmp/before.py
uv run --no-project python $S/verify_pure_move.py /tmp/before.py <package>
```

It compares every top-level definition before and after, ignoring the module qualification
and relative-import depth the split introduces, and reports anything missing, unexpected,
duplicated with drift, or changed. This is what makes a 50-file diff reviewable: "every
definition is identical" is checkable, unlike the diff. Always re-derive the before side
from git, never from your own earlier output. Re-run it after any cleanup pass.

For a test split, pass `--strip-package <package>` so the source package's module names are
normalized too.

### 6. Then the suite

```sh
hogli test <tests>/
```

Static checks cover import wiring and equivalence, not behavior. Deferred imports inside
function bodies fail at call time, so only running the tests catches a mistake there.

## Traps worth knowing

- **A re-export shim in `__init__.py`** gives every symbol two bindings, so patching one
  leaves internal callers on the real implementation: the patch applies, the test passes,
  and nothing intercepted. `.semgrep/rules/devex/no-init-reexports.yaml` already blocks
  eager re-exports repo-wide; the silent-mock failure is the extra reason not to add one.
- **Moving code makes its old semgrep findings new.** Semgrep skips its baseline comparison
  for findings in files that did not exist in the baseline commit, so every pre-existing
  violation in the moved code comes back as blocking. Check before pushing:
  `uv run --no-project --with semgrep semgrep --config .semgrep/rules/devex <package>/`.
- **Relative imports break one level down.** The script deepens them, including inside
  function bodies. A missed one is invisible until the function runs.
- **A `models.py` split is the one case that needs re-exports.** Django imports an app's
  `models` package but does not recurse into it, so model classes in submodules never reach
  the app registry and every `from ..models import Model` caller breaks. Add aggregation
  imports to `models/__init__.py`; `no-init-reexports.yaml` exempts `**/models/**` for
  exactly this reason. The script warns when it writes a `models/` package.
- **A top-level statement after the first definition stops the split.** A module-level `if`,
  an `assert`, or a registration call cannot be attributed to a concern, and copying it into
  every module would run its side effect once per module. Move it into a function or above
  the definitions first.

## Left for you

- Decide on the section dividers the move leaves behind.
- Rename locals that shadow a new module name.
- Update any doc or skill that links the old path; a split leaves dead links behind.
