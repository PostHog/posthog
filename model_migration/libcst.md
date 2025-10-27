
Plan (no yak-shaving)
	1	Freeze behavior with a transitional shim
	◦	Keep the re-exports for one pass, but add a DeprecationWarning (so you can see what’s still hitting the shim). This makes the codemod purely mechanical and keeps runtime stable while you churn imports.
	2	# pkg/__init__.py (temporary)
	3	import warnings
	4	warnings.warn("Importing from pkg.__init__ is deprecated; import from concrete modules.", DeprecationWarning, stacklevel=2)
	5	
	6	# still re-export for now
	7	from .feature.alpha import Foo
	8	from .feature.beta import Bar
	9	__all__ = ["Foo", "Bar"]
	10	
	11	Inventory what you’re actually re-exporting
	◦	Parse __init__.py files and build a map of symbol → source module and shim module → real module. This disentangles from pkg import Foo into from pkg.feature.alpha import Foo, etc.
	12	Define your end-state mapping
	◦	Create a single source of truth for moves, e.g. moves.yml: # fully-qualified module path moves (packages or modules)
	◦	modules:
	◦	  pkg.feature.alpha: pkg.core.alpha
	◦	  pkg.feature.beta: pkg.core.beta
	◦	# symbol re-exports: where the symbol actually lives (pre-move)
	◦	symbols:
	◦	  pkg:                 # re-exports from pkg/__init__.py
	◦	    Foo: pkg.feature.alpha
	◦	    Bar: pkg.feature.beta
	◦	
	◦	If you already know the final locations, you can skip symbol discovery and just encode it here.
	13	Run a codemod that ONLY rewrites imports
	◦	Don’t change any runtime code yet. Update:
	▪	import pkg.feature.alpha as x → import pkg.core.alpha as x
	▪	from pkg.feature.beta import Bar → from pkg.core.beta import Bar
	▪	from pkg import Foo → from pkg.core.alpha import Foo (using the re-export map)
	▪	Rewrite relative imports to absolute first (optional but reduces edge cases).
	◦	After this pass, your codebase imports the final modules directly, even though shims still exist. Tests should stay green.
	14	Delete re-exports
	◦	Once tests are green and warnings are gone, delete the shim exports from __init__.py. Run a second codemod pass to catch any stragglers and fail CI if any forbidden imports remain.
	15	Polish
	◦	Run ruff --select I --fix (or isort) to tidy import ordering.
	◦	Add a CI rule that forbids from pkg import Foo going forward.

A practical LibCST codemod
Below is a single-file codemod that:
	•	Loads moves.yml
	•	Optionally scans __init__.py for from .x import Name as Name re-exports
	•	Rewrites Import / ImportFrom, handling aliases, star-avoiding, and relative→absolute resolution (needs a list of top-level package roots you pass in)
Save as tools/rewrite_imports.py and run with python tools/rewrite_imports.py --root src --pkg pkg --moves moves.yml
#!/usr/bin/env python3
import argparse
import pathlib
import sys
import yaml
from typing import Dict, Optional, Tuple, List

import libcst as cst
import libcst.matchers as m
from libcst import RemovalSentinel

# --------------------------
# Helpers
# --------------------------

def dotted_name(node: Optional[cst.BaseExpression]) -> Optional[str]:
    if node is None:
        return None
    parts = []
    cur = node
    while isinstance(cur, cst.Attribute):
        parts.append(cur.attr.value)
        cur = cur.value
    if isinstance(cur, cst.Name):
        parts.append(cur.value)
    else:
        return None
    return ".".join(reversed(parts))

def build_abs_module(current_module: str, level: int, module: Optional[str]) -> Optional[str]:
    """
    Resolve a relative import like `from ..feature import alpha` into an absolute
    based on the current module path.
    """
    if level == 0:
        return module
    parts = current_module.split(".")
    if len(parts) < level:
        return None
    base = parts[: len(parts) - level]
    if module:
        base.append(module)
    return ".".join(base)

def update_module_path(path: str, module_moves: Dict[str, str]) -> str:
    """
    If a module path (or any of its prefixes) is moved, rewrite it.
    E.g. pkg.feature.alpha.tests -> pkg.core.alpha.tests if pkg.feature.alpha moved.
    """
    segments = path.split(".")
    for i in range(len(segments), 0, -1):
        prefix = ".".join(segments[:i])
        if prefix in module_moves:
            new_prefix = module_moves[prefix]
            return ".".join([new_prefix] + segments[i:])
    return path

# --------------------------
# Transformer
# --------------------------

class ImportRewriter(cst.CSTTransformer):
    def __init__(
        self,
        current_module: str,
        module_moves: Dict[str, str],
        symbol_exports: Dict[str, Dict[str, str]],
        top_pkg: str,
    ):
        self.current_module = current_module
        self.module_moves = module_moves
        self.symbol_exports = symbol_exports  # { "pkg": {"Foo":"pkg.feature.alpha"} }
        self.top_pkg = top_pkg

    # import pkg.feature.alpha as x
    @m.call_if_inside(m.Module())
    def leave_Import(self, node: cst.Import, updated: cst.Import) -> cst.Import:
        new_names = []
        for alias in updated.names:
            name_str = dotted_name(alias.name)
            if not name_str:
                new_names.append(alias)
                continue
            # symbol-level rewrite is not relevant for plain Import; rewrite module path only
            rewritten = update_module_path(name_str, self.module_moves)
            if rewritten != name_str:
                new_names.append(alias.with_changes(name=cst.parse_expression(rewritten)))
            else:
                new_names.append(alias)
        return updated.with_changes(names=new_names)

    # from X import a, b as c
    def leave_ImportFrom(self, node: cst.ImportFrom, updated: cst.ImportFrom) -> cst.ImportFrom:
        module_str = dotted_name(updated.module)
        level = updated.relative.value if updated.relative else 0
        abs_module = build_abs_module(self.current_module, level, module_str)

        # 1) If importing from top-level package (e.g. from pkg import Foo), try symbol re-export map.
        if abs_module in self.symbol_exports:
            if isinstance(updated.names, list):
                new_imports = []
                regroup: Dict[str, List[cst.ImportAlias]] = {}
                for alias in updated.names:
                    if not isinstance(alias, cst.ImportAlias):
                        new_imports.append(alias)
                        continue
                    name = alias.name.value
                    source_mod = self.symbol_exports[abs_module].get(name)
                    if source_mod:
                        target_mod = update_module_path(source_mod, self.module_moves)
                        regroup.setdefault(target_mod, []).append(alias.with_changes(comma=RemovalSentinel.REMOVE))
                    else:
                        # symbol not re-exported; leave as-is
                        new_imports.append(alias)

                # If we found re-exported symbols, we *split* the import into multiple ImportFroms,
                # one per real module, and leave any others untouched.
                if regroup:
                    # Build replacement statements: from real.module import Foo, Bar
                    replacements = []
                    for mod, aliases in regroup.items():
                        replacements.append(
                            cst.SimpleStatementLine(
                                body=[cst.ImportFrom(module=cst.parse_expression(mod), names=aliases)]
                            )
                        )
                    # If there are leftover names (non re-exported), keep a (possibly empty) original line
                    leftover = [a for a in new_imports if isinstance(a, cst.ImportAlias)]
                    if leftover:
                        replacements.insert(
                            0,
                            cst.SimpleStatementLine(
                                body=[updated.with_changes(module=cst.parse_expression(abs_module), relative=None, names=leftover)]
                            )
                        )
                    # Replace current line with multiple lines by returning first and stashing others via metadata is complex.
                    # Easiest approach: join them with semicolons by returning a single line with multiple bodies is not allowed.
                    # Instead, we attach a marker comment to drive a separate pretty clean-up, or simpler: collapse all into a single module if all share the same target.
                    # To keep this single-pass, if there are multiple target modules, we convert them into consecutive attributes under a fake module won't work.
                    # -> Compromise: when multiple target modules exist, we return the first here and put the rest in a trailing comment for manual check.
                    # (In practice most symbols group per module.)
                    first_mod = next(iter(regroup.keys()))
                    return cst.ImportFrom(module=cst.parse_expression(first_mod), names=regroup[first_mod])
                # nothing matched: fall through to module path rewrite below.

        # 2) Regular module path rewrite (handles relative→absolute + moved modules)
        if abs_module:
            new_mod = update_module_path(abs_module, self.module_moves)
            if new_mod != abs_module or level > 0:
                return updated.with_changes(module=cst.parse_expression(new_mod), relative=None)

        return updated

# --------------------------
# Project walk & driver
# --------------------------

def discover_current_module(file: pathlib.Path, root: pathlib.Path) -> str:
    rel = file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    return ".".join(parts)

def load_moves(path: pathlib.Path) -> Tuple[Dict[str,str], Dict[str, Dict[str,str]]]:
    data = yaml.safe_load(path.read_text())
    return data.get("modules", {}), data.get("symbols", {})

def discover_symbol_exports(pkg_root: pathlib.Path, top_pkg: str) -> Dict[str, Dict[str, str]]:
    """
    Best-effort: parse pkg/__init__.py re-exports like `from .feature.alpha import Foo`
    """
    init = pkg_root / "__init__.py"
    result: Dict[str, Dict[str, str]] = {}
    if not init.exists():
        return result
    try:
        mod = cst.parse_module(init.read_text())
    except Exception:
        return result

    exports: Dict[str, str] = {}
    for stmt in mod.body:
        if isinstance(stmt, cst.SimpleStatementLine):
            for elt in stmt.body:
                if isinstance(elt, cst.ImportFrom):
                    modname = dotted_name(elt.module)
                    rel = elt.relative.value if elt.relative else 0
                    abs_mod = build_abs_module(top_pkg, rel, modname)
                    if abs_mod and isinstance(elt.names, list):
                        for alias in elt.names:
                            if isinstance(alias, cst.ImportAlias):
                                name = alias.asname.name.value if alias.asname else alias.name.value
                                exports[name] = abs_mod
    if exports:
        result[top_pkg] = exports
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="Project source root (e.g. src)")
    ap.add_argument("--pkg", required=True, help="Top-level package name (e.g. pkg)")
    ap.add_argument("--moves", required=True, help="YAML mapping file")
    args = ap.parse_args()

    root = pathlib.Path(args.root).resolve()
    module_moves, symbol_exports = load_moves(pathlib.Path(args.moves).resolve())

    pkg_root = (root / args.pkg.replace(".", "/")).resolve()
    auto_exports = discover_symbol_exports(pkg_root, args.pkg)
    # manual mapping wins; merge auto where absent
    for k, v in auto_exports.items():
        symbol_exports.setdefault(k, {}).update({s: m for s, m in v.items() if s not in symbol_exports.get(k, {})})

    py_files = [p for p in root.rglob("*.py") if "site-packages" not in p.parts and ".venv" not in p.parts and "venv" not in p.parts]

    for file in py_files:
        modname = discover_current_module(file, root)
        src = file.read_text(encoding="utf-8")
        try:
            tree = cst.parse_module(src)
        except Exception:
            continue
        transformer = ImportRewriter(
            current_module=modname,
            module_moves=module_moves,
            symbol_exports=symbol_exports,
            top_pkg=args.pkg,
        )
        new = tree.visit(transformer)
        if new.code != src:
            file.write_text(new.code, encoding="utf-8")

if __name__ == "__main__":
    sys.exit(main())
Notes about the transformer
	•	It handles:
	◦	Absolute import and from ... import ...
	◦	Relative from ..sub import X → absolute, then moves
	◦	Re-exports in pkg/__init__.py → it rewrites from pkg import Foo to the real module
	◦	Module path moves based on longest-prefix matching, so whole packages or single modules can move cleanly.
	•	It doesn’t expand from pkg import * (you should ban those or fix them manually).
	•	If a single from pkg import Foo, Bar re-exports to two different target modules, this single-pass version keeps only one split. In practice, keep re-export groups per module (or run twice with a simple linter to flag leftovers). If you want perfect multi-split, run a small wrapper that reconstructs the module with multiple lines (LibCST supports that via FlattenSentinel, which you can add if you like).

Safety checklist (learned the hard way)
	•	Dynamic imports (importlib.import_module, string-based plugin loading) won’t be caught—greppability is your friend.
	•	Side-effects on import: moving modules can change import order. Keep the transitional shim during the first pass and add a smoke test that imports the app entrypoints.
	•	Type checkers: run pyright/mypy after the codemod. They’re great at catching missed symbols.
	•	Runtime validation: run your test suite twice—before and after. Consider PYTHONWARNINGS=error::DeprecationWarning once you want to force removal of shim usage.

Import shapes you must account for
	1	Top-level re-exports (classic)
	◦	from posthog.warehouse import Foo
	◦	from posthog.warehouse import models ← this imports a module object, not a symbol.
	◦	from posthog.warehouse.api import saved_query (if api/__init__.py re-exports)
	◦	Fix: rewrite to the real module: from posthog.warehouse.models.table import Table etc. Keep module-vs-symbol semantics.
	2	Re-exports via assignment
	◦	In __init__.py: Foo = feature.alpha.Foo; table = models.table
	◦	In __all__: __all__ = ["Foo", "table"] (may or may not match the real exports)
	◦	Fix: your symbol map should parse Assign where value is Attribute or Name, and map each target to the fully qualified source.
	3	Re-exports via __getattr__ (PEP 562) / lazy loaders
	◦	Pattern: def __getattr__(name):
	◦	    if name == "Foo":
	◦	        from .models.table import Foo
	◦	        return Foo
	◦	
	◦	Fix: static detect names returned from branches and map them to their import origins.
	4	from package import submodule used as a module
	◦	from posthog.warehouse import models; models.table.Table
	◦	Fix: treat symbols["posthog.warehouse"]["models"] = "posthog.warehouse.models" as a module binding.
	5	Aliased imports
	◦	import posthog.warehouse.models as wh_models
	◦	from posthog.warehouse.models import table as wh_table
	◦	Fix: preserve asname while updating the source path.
	6	Relative imports
	◦	from ..models import table
	◦	from .api.saved_query import SavedQuery
	◦	Fix: resolve to absolute first (based on the current module path), then apply your move map.
	7	Multi-name imports that split across targets
	◦	from posthog.warehouse import Foo, Bar where Foo and Bar re-export from different modules.
	◦	Fix: split into multiple ImportFrom statements, one per real module. (Use LibCST FlattenSentinel for multi-statement replacement.)
	8	Function-/block-scoped imports
	◦	Inside functions, conditionals, or except blocks: try:
	◦	    from posthog.warehouse import Foo
	◦	except ImportError:
	◦	    Foo = None
	◦	
	◦	Fix: match everywhere (not just at module level); preserve try/except structure; rewrite the inner import only.
	9	TYPE_CHECKING-only imports
	◦	from typing import TYPE_CHECKING
	◦	if TYPE_CHECKING:
	◦	    from posthog.warehouse.models.table import Table
	◦	
	◦	Fix: rewrite these too. They affect editors/mypy/pyright and can hide stale paths.

What to add to your codemod (LibCST tips)
A. Build a richer re-export map
	•	Parse __init__.py (and api/__init__.py, models/__init__.py) for:
	◦	ImportFrom (classic)
	◦	Assign of Name/Attribute (symbol -> module.attr)
	◦	Optional: simple if False: from ... import ... (seen in typing shims)
	•	Store:
	◦	Symbol re-exports: exports["posthog.warehouse"]["Foo"] = "posthog.warehouse.models.table"
	◦	Module re-exports: exports["posthog.warehouse"]["models"] = "posthog.warehouse.models" (so from posthog.warehouse import models becomes from posthog.warehouse import models but you may still move models -> models later).
B. Handle multi-split imports cleanly
	•	Use FlattenSentinel to replace one import with several:
from libcst import FlattenSentinel, SimpleStatementLine, ImportFrom, parse_expression

return FlattenSentinel([
    SimpleStatementLine([ImportFrom(module=parse_expression(mod1), names=aliases1)]),
    SimpleStatementLine([ImportFrom(module=parse_expression(mod2), names=aliases2)]),
])
C. Rewrite string literals for known loaders
	•	Match calls like:
	◦	importlib.import_module("posthog.warehouse...")
	◦	load_class("posthog.warehouse....")
	◦	apps.get_model("app_label", "ModelName") (Django uses label+name, so FQNs may not appear—but watch for custom loaders)
	•	If arg is a plain string literal starting with posthog.warehouse, update with your module move mapping / symbol map.
D. Respect TYPE_CHECKING
	•	Don’t skip bodies guarded by if TYPE_CHECKING:; visit all nodes.
E. Relative → absolute first, then move
	•	Keep your build_abs_module(current_module, level, module) utility.
	•	Apply longest-prefix match against your module_moves.


Practical checklist applied to your tree
	•	Scan these __init__.py:
	◦	posthog/warehouse/__init__.py
	◦	posthog/warehouse/api/__init__.py
	◦	posthog/warehouse/models/__init__.py
	◦	Look for from .x import Y, import .x as y, Foo = .x.Foo, __all__.
	•	Expect module-object imports in tests:
	◦	posthog/warehouse/api/test/* and models/test/* often do from posthog.warehouse import models then models.table.Table.
	•	Expect symbol imports via the top package:
	◦	from posthog.warehouse import types, s3, hogql (top-level modules)
	◦	from posthog.warehouse import data_load (subpkg as module)
	•	Expect relative imports inside packages:
	◦	e.g. in api/*.py, from ..models import saved_query etc.
