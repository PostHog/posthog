"""``owners:fmt`` — a dry-run canonical file-placement oracle.

Ownership is a piecewise-constant function on the directory tree: most of the
tree shares its parent's owners, and a handful of *change points* (boundaries)
flip to a new owner set. A ``match``/``owners`` statement encodes exactly one
such boundary. Which physical ``owners.yaml`` file carries a given statement is
pure presentation — a parent rule ``- match: '/hogql/'`` resolves identically to
a child ``owners.yaml`` under nearest-wins.

``fmt`` computes the *canonical* layout — the placement of statements onto files
that minimizes a facility-location cost — and reports how the current layout
differs. It is an oracle: it NEVER writes. There is no ``--write`` flag. Fold and
split suggestions from ``owners:lint`` are the everyday incremental mechanism
(with hysteresis); ``fmt`` is the drift oracle you consult deliberately.

The cost model (module constants, tunable — "optimal" is relative to them):

* ``ALPHA`` — the price of a dedicated simple ``owners.yaml`` existing at all.
  Pinned carriers (``product.yaml`` manifests, non-simple ``owners.yaml``,
  glob-bearing files, the repo root) cost nothing: they exist anyway.
* ``GAMMA`` — the per-level price of carrying a statement as a rule in an
  ancestor instead of at its own directory (tree distance).
* ``MAX_RULES`` — a file may hold at most this many statements; a denser cluster
  forces a dedicated child file (the split case).

Placement is a bottom-up capacitated facility-location DP over the directory
tree. The result is proven: the proposed layout is simulated in memory and every
tracked path re-resolved; it must match the current resolution exactly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from .matcher import compile_pattern
from .resolver import OWNERS_FILENAME, PRODUCT_FILENAME, OwnersFile, OwnersResolver, ParsedOwnershipFile
from .schema import OwnersRule, _Unset, is_simple_owners_file, match_is_glob

# Cost model. "Canonical" is optimal only relative to these; tune to taste.
ALPHA = 8  # cost of a dedicated simple owners.yaml existing
GAMMA = 1  # per-level cost of carrying a statement as an ancestor rule
# Soft cap on statements per file before a split is attempted. Sized to the largest
# hand-accepted rules block in the repo (frontend/src/scenes carries ~60); a split
# only happens when a whole subtree of rules can move together — singleton rules are
# never exiled to per-dir files, so overflow past the cap is tolerated.
MAX_RULES = 100

# Sentinel carry distance meaning "no usable ancestor" — large enough that opening a
# dedicated file (ALPHA) always beats carrying even a single statement this far.
_BLOCKED = 10**6


# An owner set is an ordered tuple of slugs, or None for unowned/no-contribution.
OwnerSet = tuple[str, ...] | None

# Explicit `owners: null` (unowned-by-design, coverage-exempt) is a distinct
# resolution outcome from plain unowned. It flows through labeling, placement,
# and the proof as this sentinel owner set, so a plan can never trade the
# exemption away for bare unownedness without the proof noticing.
UNOWNED_BY_DESIGN: tuple[str, ...] = ("<unowned-by-design>",)


def _resolution_owner_set(owners: list[str] | None, unowned_by_design: bool) -> OwnerSet:
    if unowned_by_design:
        return UNOWNED_BY_DESIGN
    return tuple(owners) if owners else None


def _statement_owners_value(owners: OwnerSet) -> list[str] | None:
    """The `owners:` value a statement writes into a file or rule — the sentinel
    materializes as an explicit `owners: null`."""
    return None if owners is None or owners == UNOWNED_BY_DESIGN else list(owners)


def _is_simple_file(f: OwnersFile | None) -> bool:
    """A file fmt may rewrite/relocate — the shared predicate, admitting anchored
    rules since fmt reasons about statements."""
    return is_simple_owners_file(f, allow_anchored_rules=True)


@dataclass
class _Node:
    """One directory in the tree fmt reasons over."""

    path: str  # repo-relative posix dir ("" = root)
    depth: int
    children: dict[str, _Node] = field(default_factory=dict)
    label: OwnerSet = None  # canonical owner set for files directly in this dir
    # Statements that originate at this directory (dir-context flip + file flips).
    statements: list[_Statement] = field(default_factory=list)
    pinned: bool = False  # a product.yaml / non-simple owners.yaml carrier lives here (absorbs rules)
    pinned_label: OwnerSet = None  # owners the pinned file already provides here
    frozen: bool = False  # a glob-bearing file lives here: untouched, never a carrier
    alias: bool = False  # the pin is a product.yaml manifest: only its owners list is read,
    # so it can never physically carry rules — placements must land elsewhere


@dataclass
class _Statement:
    """One boundary to encode: give ``target`` the owner set ``owners``."""

    target: str  # repo-relative dir or file path the statement applies to
    is_dir: bool
    owners: OwnerSet
    node: str  # the directory node this statement is anchored at


@dataclass
class _Placement:
    """Where a statement ends up in the canonical layout."""

    statement: _Statement
    carrier_dir: str  # directory whose file carries it
    distance: int


@dataclass
class CanonicalPlan:
    """The result of a fmt run: the canonical placement plus a diff vs. current.
    A plan only exists once the equivalence proof has passed — ``build`` raises
    otherwise — so holding a plan means the layout is proven sound."""

    current_cost: int
    canonical_cost: int
    creations: list[str]
    deletions: list[str]
    additions: dict[str, list[str]]  # file -> human-readable rule lines added

    @property
    def is_canonical(self) -> bool:
        return not self.creations and not self.deletions and not self.additions


class CanonicalPlacer:
    """Builds the canonical layout for a repo and diffs it against the current one."""

    def __init__(self, resolver: OwnersResolver) -> None:
        self.resolver = resolver
        self.repo_root = resolver.repo_root

    # --- tree + labeling -------------------------------------------------

    def _build_tree(self, file_owners: dict[str, OwnerSet]) -> _Node:
        root = _Node(path="", depth=0)
        for path in file_owners:
            parts = path.split("/")
            node = root
            acc: list[str] = []
            for part in parts[:-1]:
                acc.append(part)
                key = part
                if key not in node.children:
                    node.children[key] = _Node(path="/".join(acc), depth=node.depth + 1)
                node = node.children[key]
        return root

    def _dir_files(self, file_owners: dict[str, OwnerSet]) -> dict[str, list[tuple[str, OwnerSet]]]:
        by_dir: dict[str, list[tuple[str, OwnerSet]]] = {}
        for path, owners in file_owners.items():
            d = path.rsplit("/", 1)[0] if "/" in path else ""
            by_dir.setdefault(d, []).append((path, owners))
        return by_dir

    def _label_tree(self, node: _Node, by_dir: dict[str, list[tuple[str, OwnerSet]]]) -> None:
        """Bottom-up labeling that minimizes boundaries. Each dir takes the owner set
        held by the most of its *immediate* children and direct files — each becomes a
        boundary only if it disagrees, so this is the local min-boundary choice.

        Pinned and frozen dirs isolate: they carry their own owners (a ``product.yaml``
        manifest, a glob file) and do not vote in their parent, so a manifest at
        ``products/foo`` keeps ownership there instead of floating a rule up the tree."""
        for child in node.children.values():
            self._label_tree(child, by_dir)

        # A frozen dir labels itself from its own file too: its direct files are
        # glob-served and excluded from voting, so deriving the label from children
        # would float a bogus dir-statement above the frozen file, where the
        # nearer file shadows it and the proof fails.
        if node.pinned or node.frozen:
            node.label = node.pinned_label
            return

        votes: dict[OwnerSet, int] = {}
        for child in node.children.values():
            if child.pinned or child.frozen:
                continue  # isolated subtree — does not sway the parent
            votes[child.label] = votes.get(child.label, 0) + 1
        for _path, owners in by_dir.get(node.path, []):
            votes[owners] = votes.get(owners, 0) + 1

        # Deterministic plurality: max votes, tie-break None first then lexicographic.
        def sort_key(item: tuple[OwnerSet, int]) -> tuple[int, int, tuple[str, ...]]:
            owners, n = item
            return (-n, 0 if owners is None else 1, owners or ())

        node.label = min(votes.items(), key=sort_key)[0] if votes else None

    # --- boundaries → statements ----------------------------------------

    def _collect_statements(
        self, node: _Node, parent_label: OwnerSet, by_dir: dict[str, list[tuple[str, OwnerSet]]]
    ) -> None:
        if node.label != parent_label:
            node.statements.append(_Statement(target=node.path, is_dir=True, owners=node.label, node=node.path))
        for path, owners in sorted(by_dir.get(node.path, [])):
            if owners != node.label:
                node.statements.append(_Statement(target=path, is_dir=False, owners=owners, node=node.path))
        for child in sorted(node.children.values(), key=lambda c: c.path):
            self._collect_statements(child, node.label, by_dir)

    # --- classification: pinned carriers vs frozen glob files ------------

    def _classify(
        self, entries: list[ParsedOwnershipFile]
    ) -> tuple[dict[str, OwnerSet], dict[str, OwnerSet], set[str]]:
        """Classify the parsed ownership files. Returns (pinned_carriers, frozen_dirs
        mapped to their file's own top-level owner set, alias_dirs).

        Pinned carriers (``product.yaml`` with owners, or a non-simple owners.yaml
        with status/inherit) absorb statements for free. Frozen dirs host a
        glob-bearing file — crosscutting, untouched, never a carrier. Alias dirs are
        the product.yaml subset of pinned: the manifest provides its dir's owners but
        physically cannot hold rules (only its ``owners:`` list is read), so
        placements must land elsewhere."""
        pinned: dict[str, OwnerSet] = {}
        frozen: dict[str, OwnerSet] = {}
        alias: set[str] = set()
        for entry in entries:
            parsed = entry.parsed
            if entry.name == PRODUCT_FILENAME:
                if parsed and parsed.owners:
                    pinned[entry.rel_dir] = tuple(parsed.owners)
                    alias.add(entry.rel_dir)
                continue
            if parsed is None:
                continue
            if any(match_is_glob(r.match) for r in parsed.rules):
                frozen[entry.rel_dir] = _resolution_owner_set(parsed.owners, parsed.owners is None)
            elif not _is_simple_file(parsed):
                pinned[entry.rel_dir] = _resolution_owner_set(parsed.owners, parsed.owners is None)
        return pinned, frozen, alias

    def _apply_classification(
        self, node_index: dict[str, _Node], pinned: dict[str, OwnerSet], frozen: dict[str, OwnerSet], alias: set[str]
    ) -> None:
        for d, owners in pinned.items():
            node = node_index.get(d)
            if node is not None:
                node.pinned = True
                node.pinned_label = owners
                node.alias = d in alias
        for d, owners in frozen.items():
            node = node_index.get(d)
            if node is not None:
                node.frozen = True
                node.pinned_label = owners

    # --- facility-location DP -------------------------------------------

    def _facility_cost(self, node: _Node) -> int:
        """Price of a file existing at this directory. Free for pinned carriers and
        the repo root (they exist anyway); ALPHA for a dedicated simple file."""
        return 0 if (node.pinned or node.path == "") else ALPHA

    def _plan_placements(self, root: _Node) -> tuple[list[_Placement], set[str]]:
        """Bottom-up capacitated facility location. Returns statement placements and
        the set of directories whose file is open in the canonical layout."""
        open_dirs: set[str] = set()
        placements: list[_Placement] = []

        # memo[(path, d)] = (min cost, opens) — reconstruct is a pure lookup of the
        # decision cost() already made, so the two can never disagree.
        memo: dict[tuple[str, int], tuple[int, bool]] = {}

        def cost(node: _Node, d: int) -> tuple[int, bool]:
            """Min cost to serve node's subtree given the nearest open facility sits
            ``d`` levels above node (``d`` unused when node opens), plus whether the
            node opens its own facility. A ``d`` of ``_BLOCKED`` or more means no
            usable ancestor exists (an alias manifest or frozen glob file shadows
            everything above by nearest-file-wins), which prices carry-up out so
            the subtree opens its own facility."""
            key = (node.path, d)
            if key in memo:
                return memo[key]
            n_here = sum(1 for s in node.statements if not self._served_by_pin(node, s))

            forced_open = (node.pinned and not node.alias) or node.path == ""
            # Statements below an alias or a frozen file can never live above it:
            # the nearer file's own fields (or its untouchable globs) would shadow
            # any ancestor rule under nearest-file-wins.
            child_d = _BLOCKED if node.alias or node.frozen else d + 1
            # Option A: do not open here; carry own statements up ``d`` levels.
            carry_up = GAMMA * d * n_here + sum(cost(c, child_d)[0] for c in node.children.values())
            if (node.frozen or node.alias) and not forced_open:
                # A glob file or product.yaml manifest lives here — it can never carry
                # new rules; statements pass through.
                memo[key] = (carry_up, False)
                return memo[key]
            # Option B: open here; own statements are free, children are one level down.
            open_here = self._facility_cost(node) + sum(cost(c, 1)[0] for c in node.children.values())
            opens = forced_open or open_here <= carry_up
            memo[key] = (open_here if opens else carry_up, opens)
            return memo[key]

        def reconstruct(node: _Node, d: int, nearest_open: str) -> None:
            _best, opens = cost(node, d)
            movable = [s for s in node.statements if not self._served_by_pin(node, s)]
            if opens:
                open_dirs.add(node.path)
                for s in movable:
                    placements.append(_Placement(statement=s, carrier_dir=node.path, distance=0))
                for c in node.children.values():
                    reconstruct(c, 1, node.path)
            else:
                child_d = _BLOCKED if node.alias or node.frozen else d + 1
                for s in movable:
                    placements.append(_Placement(statement=s, carrier_dir=nearest_open, distance=d))
                for c in node.children.values():
                    reconstruct(c, child_d, nearest_open)

        cost(root, 0)
        reconstruct(root, 0, "")
        self._enforce_capacity(root, placements, open_dirs)
        return placements, open_dirs

    def _served_by_pin(self, node: _Node, s: _Statement) -> bool:
        """A dir-context statement whose owners already match the pinned carrier at
        that very directory needs no rule — the manifest/non-simple file provides it."""
        return s.is_dir and (node.pinned or node.frozen) and node.pinned_label == s.owners

    def _enforce_capacity(self, root: _Node, placements: list[_Placement], open_dirs: set[str]) -> None:
        """If a carrier exceeds MAX_RULES, open the child prefix with the most overflow
        as a dedicated facility and reassign its statements there. Repeat to a fixpoint."""
        node_index: dict[str, _Node] = {}
        _index(root, node_index)

        def can_host(d: str) -> bool:
            node = node_index.get(d)
            return node is None or not (node.frozen or node.alias)

        changed = True
        while changed:
            changed = False
            by_carrier: dict[str, list[_Placement]] = {}
            for p in placements:
                by_carrier.setdefault(p.carrier_dir, []).append(p)
            for carrier, ps in by_carrier.items():
                if len(ps) <= MAX_RULES:
                    continue
                # Group overflow by the immediate child-of-carrier prefix. Only
                # statements that live under a real subdirectory can move to a child
                # facility — a direct file (``/x.tsx``) has no subdir to hold it, the
                # carrier's own top-level statement (empty head) stays put, and a dir
                # hosting a glob file or product.yaml manifest cannot take new rules.
                # The cap is soft: a group of one is never exiled to a per-dir file
                # (that recreates the single-purpose sprawl fmt exists to remove), so
                # if no group has at least two statements the overflow is tolerated.
                groups: dict[str, list[_Placement]] = {}
                for p in ps:
                    rel = p.statement.target[len(carrier) + 1 :] if carrier else p.statement.target
                    head = rel.split("/", 1)[0]
                    if head and (p.statement.is_dir or "/" in rel):
                        groups.setdefault(head, []).append(p)
                hostable = [h for h in groups if len(groups[h]) >= 2 and can_host(f"{carrier}/{h}" if carrier else h)]
                best_head = max(hostable, key=lambda h: len(groups[h]), default=None)
                if best_head is None:
                    continue
                new_dir = f"{carrier}/{best_head}" if carrier else best_head
                open_dirs.add(new_dir)
                for p in groups[best_head]:
                    p.carrier_dir = new_dir
                    p.distance = _depth(p.statement.target) - _depth(new_dir) - (0 if p.statement.is_dir else 1)
                    if p.distance < 0:
                        p.distance = 0
                changed = True

    # --- current layout cost + diff -------------------------------------

    def build(self) -> CanonicalPlan:
        entries = self.resolver.parsed_ownership_files()  # the single parse pass
        pinned, frozen, alias = self._classify(entries)
        # One definition of "a carrier file already exists here": the _classify one.
        pinned_dirs = set(pinned) | set(frozen)

        tracked = self.resolver.tracked_files()
        code_files = [p for p in tracked if p.rsplit("/", 1)[-1] not in (OWNERS_FILENAME, PRODUCT_FILENAME)]
        # Every file's (owners, status) — the proof compares both: placement only
        # models owners, so a fold that reorders past a status rule must fail the
        # proof rather than silently drop generated/vendored from a subtree.
        all_owners: dict[str, tuple[OwnerSet, str]] = {}
        label_owners: dict[str, OwnerSet] = {}  # excludes glob-painted files, which stay frozen
        for p in code_files:
            r = self.resolver.resolve(p)
            owners = _resolution_owner_set(r.owners, r.unowned_by_design)
            all_owners[p] = (owners, r.status)
            # A file whose owners come from a glob in a frozen file stays frozen — keep
            # it out of labeling. Unowned files (no source) are never glob-served.
            glob_served = False
            if r.source is not None:
                source_dir = r.source.rsplit("/", 1)[0] if "/" in r.source else ""
                glob_served = source_dir in frozen
            if not glob_served:
                label_owners[p] = owners

        root = self._build_tree(label_owners)
        node_index: dict[str, _Node] = {}
        _index(root, node_index)
        by_dir = self._dir_files(label_owners)
        self._apply_classification(node_index, pinned, frozen, alias)
        self._label_tree(root, by_dir)
        self._collect_statements(root, None, by_dir)

        placements, open_dirs = self._plan_placements(root)
        proposed = self._proposed_files(entries, placements, open_dirs)
        self._prove(proposed, all_owners)  # raises on any resolution mismatch

        creations, deletions, additions = self._diff(entries, proposed, open_dirs, pinned_dirs, code_files)
        return CanonicalPlan(
            current_cost=self._current_cost(entries),
            canonical_cost=self._layout_cost(open_dirs, placements, pinned_dirs),
            creations=creations,
            deletions=deletions,
            additions=additions,
        )

    def _layout_cost(self, open_dirs: set[str], placements: list[_Placement], pinned_dirs: set[str]) -> int:
        # A dedicated file costs ALPHA; the root and pinned carriers are free.
        total = sum(ALPHA for d in open_dirs if d != "" and d not in pinned_dirs)
        total += sum(GAMMA * p.distance for p in placements)
        return total

    def _current_cost(self, entries: list[ParsedOwnershipFile]) -> int:
        """Cost of the layout as it stands: ALPHA per dedicated simple file, plus the
        carry distance of every statement each file currently holds as a rule."""
        total = 0
        for entry in entries:
            if entry.name == PRODUCT_FILENAME or entry.parsed is None:
                continue
            parsed = entry.parsed
            if _is_simple_file(parsed) and entry.rel_dir != "":
                total += ALPHA
            for rule in parsed.rules:
                if match_is_glob(rule.match):
                    continue
                target = rule.match.strip("/")
                total += GAMMA * max(0, len(target.split("/")) - (0 if rule.match.endswith("/") else 1))
        return total

    def _proposed_files(
        self, entries: list[ParsedOwnershipFile], placements: list[_Placement], open_dirs: set[str]
    ) -> dict[str, OwnersFile]:
        """Materialize the proposed layout as in-memory OwnersFile objects, keyed by
        directory. Pinned files are carried over verbatim (as copies, since rules are
        appended) and augmented with their placements."""
        files: dict[str, OwnersFile] = {}
        for entry in entries:
            parsed = entry.parsed
            if parsed is None:
                continue
            if entry.name == PRODUCT_FILENAME:
                files[entry.rel_dir] = parsed  # aliases never receive placements
            elif not _is_simple_file(parsed):
                # Copy: placements are appended, and the parsed entries are cached.
                files[entry.rel_dir] = replace(parsed, rules=list(parsed.rules))

        for carrier in open_dirs:
            if carrier not in files:
                files[carrier] = OwnersFile(
                    path=self.repo_root / carrier / OWNERS_FILENAME, directory=carrier, owners=[]
                )
        for p in placements:
            carrier = p.carrier_dir
            f = files[carrier]
            rel = p.statement.target[len(carrier) + 1 :] if carrier else p.statement.target
            match = f"/{rel}/" if p.statement.is_dir and rel else ("/" if not rel else f"/{rel}")
            if p.statement.is_dir and not rel:
                f.owners = _statement_owners_value(p.statement.owners)
                continue
            f.rules.append(OwnersRule(match=match, owners=_statement_owners_value(p.statement.owners)))
        return files

    def _diff(
        self,
        entries: list[ParsedOwnershipFile],
        proposed: dict[str, OwnersFile],
        open_dirs: set[str],
        pinned_dirs: set[str],
        code_files: list[str],
    ) -> tuple[list[str], list[str], dict[str, list[str]]]:
        current_simple_dirs: set[str] = set()  # dirs whose file fmt may delete
        # dir -> {match: owners as written} — last occurrence wins, mirroring the
        # resolver's last-match-wins so the diff compares against what decides.
        current_rules: dict[str, dict[str, list[str] | None | _Unset]] = {}
        current_owners: dict[str, list[str] | None] = {}  # dir -> top-level owners as written
        for entry in entries:
            if entry.name != OWNERS_FILENAME or entry.parsed is None:
                continue
            current_rules[entry.rel_dir] = {r.match: r.owners for r in entry.parsed.rules}
            current_owners[entry.rel_dir] = entry.parsed.owners
            if _is_simple_file(entry.parsed):
                current_simple_dirs.add(entry.rel_dir)

        creations, deletions = [], []
        additions: dict[str, list[str]] = {}

        for carrier in sorted(open_dirs):
            proposed_file = proposed[carrier]
            proposed_rules = {r.match: r.owners for r in proposed_file.rules}
            cur_rules = current_rules.get(carrier, {})
            path = f"{carrier}/{OWNERS_FILENAME}" if carrier else OWNERS_FILENAME
            file_exists = carrier in current_rules or carrier in pinned_dirs
            # A new file matters if it carries rules OR contributes owners itself
            # (a non-empty list, or explicit null); owners: [] with no rules is a no-op.
            has_content = bool(proposed_file.rules) or bool(proposed_file.owners) or proposed_file.owners is None
            if not file_exists and has_content:
                creations.append(path)
            edits: list[str] = []
            # Changed top-level `owners:` and reused-match rules with different
            # owners are as much a part of the plan as new rules — omitting either
            # would print a plan that, applied literally, resolves differently
            # from the proved proposal.
            if carrier in current_owners and proposed_file.owners != current_owners[carrier]:
                edits.append(f"owners: {_fmt_owners(current_owners[carrier])} -> {_fmt_owners(proposed_file.owners)}")
            changed: list[str] = []
            added: list[str] = []
            for m, o in proposed_rules.items():
                if m not in cur_rules:
                    added.append(f"{m} -> {_fmt_owners(o)}")
                elif o != cur_rules[m]:
                    changed.append(f"{m}: {_fmt_owners(cur_rules[m])} -> {_fmt_owners(o)}")
            removed: list[str] = []
            # Rebuilt simple carriers can shed rules the canonical layout proved
            # redundant; those drops are part of the plan too. Rules that match no
            # code file under the carrier stay silent — they act outside fmt's
            # domain (e.g. the root rule routing owners.yaml edits) and the proof
            # never reasons about them, so fmt must not propose touching them.
            if carrier not in pinned_dirs:
                for m in cur_rules.keys() - proposed_rules.keys():
                    matcher = compile_pattern(m)
                    prefix = f"{carrier}/" if carrier else ""
                    in_domain = any(
                        matcher.test(p[len(prefix) :]) for p in code_files if not prefix or p.startswith(prefix)
                    )
                    if in_domain:
                        removed.append(f"drop {m} (was {_fmt_owners(cur_rules[m])})")
            edits += sorted(changed) + sorted(added) + sorted(removed)
            if edits:
                additions[path] = edits

        for carrier in current_simple_dirs:
            if carrier not in open_dirs:
                deletions.append(f"{carrier}/{OWNERS_FILENAME}" if carrier else OWNERS_FILENAME)

        return sorted(creations), sorted(deletions), additions

    # --- equivalence proof ----------------------------------------------

    def _prove(self, proposed: dict[str, OwnersFile], file_owners: dict[str, tuple[OwnerSet, str]]) -> None:
        """Re-resolve every tracked path against the proposed layout; raises on any
        owners or status mismatch with the current resolution."""
        sim = _InMemoryResolver(self.repo_root, proposed)
        for path, expected in file_owners.items():
            got = sim.resolve(path)
            got_pair = (_resolution_owner_set(got.owners, got.unowned_by_design), got.status)
            if got_pair != expected:
                raise AssertionError(f"fmt bug: canonical layout resolves {path} to {got_pair}, expected {expected}")


class _InMemoryResolver(OwnersResolver):
    """An OwnersResolver that reads ownership files from an in-memory map instead of
    disk — used to prove the proposed layout resolves identically."""

    def __init__(self, repo_root: Path, files: dict[str, OwnersFile]) -> None:
        self.repo_root = repo_root
        self._dir_cache = {}
        self._teams_cache = None
        self._files = files

    def _load_dir_file(self, directory: str) -> OwnersFile | None:  # type: ignore[override]
        return self._files.get(directory)


def _depth(path: str) -> int:
    return 0 if path == "" else len(path.split("/"))


def _index(node: _Node, out: dict[str, _Node]) -> None:
    out[node.path] = node
    for c in node.children.values():
        _index(c, out)


def _fmt_owners(owners: list[str] | None | _Unset) -> str:
    if isinstance(owners, _Unset):
        return "(inherit)"
    if owners is None:
        return "(unowned)"
    return "[" + ", ".join(owners) + "]"
