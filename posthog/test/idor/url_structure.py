"""
Parse DRF URL regexes into structured URLStructure objects.

The regex-based parser is the one fragile component of the IDOR test
infrastructure. This module isolates it, with unit tests at
`test_url_structure.py`, so a malformed pattern never causes incorrect
tests — parsing just returns None and the viewset ends up in the skip
report.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# The drf-extensions nested router always prefixes parent kwargs with this literal.
PARENT_KWARG_PREFIX = "parent_lookup_"

# Root parents correspond to the top-level registrations in
# `posthog/api/__init__.py`: `projects_router`, `environments_router`,
# and the `organizations` route (registered at various points).
VALID_ROOT_PARENTS = frozenset({"projects", "environments", "organizations"})

# Named groups we consider "final" (identifier of the detail resource).
# DRF's `lookup_url_kwarg` defaults to "pk", but individual viewsets can
# override it (e.g. FeatureFlagViewSet might use short_id). Anything that
# isn't `format` and isn't prefixed `parent_lookup_` is treated as a pk.
_NON_PK_KWARGS = frozenset({"format"})


@dataclass(frozen=True)
class URLStructure:
    """Structured breakdown of a DRF detail URL regex.

    Examples of patterns that parse successfully:

        ^projects/(?P<parent_lookup_project_id>[^/.]+)/annotations/(?P<pk>[^/.]+)/?$
            → URLStructure(root='projects', root_kwarg='parent_lookup_project_id',
                           intermediate_parents=[], resource_prefix='annotations',
                           pk_kwarg='pk')

        ^environments/(?P<parent_lookup_team_id>[^/.]+)/batch_exports/(?P<parent_lookup_batch_export_id>[^/.]+)/runs/(?P<pk>[^/.]+)/?$
            → URLStructure(root='environments', root_kwarg='parent_lookup_team_id',
                           intermediate_parents=[('batch_exports', 'parent_lookup_batch_export_id')],
                           resource_prefix='runs', pk_kwarg='pk')
    """

    root: str
    root_kwarg: str
    resource_prefix: str
    pk_kwarg: str
    intermediate_parents: list[tuple[str, str]] = field(default_factory=list)

    def build_url(
        self, *, root_id: int | str, pk: int | str, intermediate_ids: Optional[dict[str, int | str]] = None
    ) -> str:
        """Construct a concrete URL from this structure.

        `intermediate_ids` maps each intermediate parent's kwarg name to an id.
        """
        parts: list[str] = ["api", self.root, str(root_id)]
        for prefix, kwarg in self.intermediate_parents:
            if intermediate_ids is None or kwarg not in intermediate_ids:
                raise KeyError(f"URLStructure.build_url requires an id for intermediate parent kwarg {kwarg!r}")
            parts.append(prefix)
            parts.append(str(intermediate_ids[kwarg]))
        parts.append(self.resource_prefix)
        parts.append(str(pk))
        return "/" + "/".join(parts) + "/"

    @property
    def required_intermediate_kwargs(self) -> list[str]:
        return [kwarg for (_, kwarg) in self.intermediate_parents]


_NAMED_GROUP_RE = re.compile(r"\(\?P<([^>]+)>[^)]+\)")


def parse_url_pattern(regex_str: str) -> Optional[URLStructure]:
    """Parse a DRF detail URL regex into a URLStructure.

    Returns None for patterns that are:
      - not detail URLs (no pk kwarg)
      - format variants (pk kwarg is literally `format`)
      - structurally unusual (don't follow the standard DRF-extensions layout)

    The caller treats None as "not auto-testable" and records the viewset as
    skipped, so the only downside of returning None is a missed opportunity —
    never a false test result.
    """
    # Strip start/end anchors, trailing optional slash
    s = regex_str
    if s.startswith("^"):
        s = s[1:]
    if s.endswith("$"):
        s = s[:-1]
    # Drop trailing `/?` and any final literal `/`
    while s.endswith("?") or s.endswith("/"):
        s = s[:-1]

    # Pattern must start with one of the root parent prefixes followed by a kwarg
    # OR be a flat (non-nested) viewset. For flat viewsets we return None since
    # they can't be IDOR-tested by URL scoping (there's no tenant id in the URL).
    root_match = re.match(r"^([a-z_]+)/\(\?P<([^>]+)>[^)]+\)", s)
    if not root_match:
        return None

    root = root_match.group(1)
    root_kwarg = root_match.group(2)
    if root not in VALID_ROOT_PARENTS:
        return None
    if not root_kwarg.startswith(PARENT_KWARG_PREFIX):
        return None

    # Parse the remainder after the root parent into an alternating sequence of
    # literal text segments and named capture groups.
    remainder = s[root_match.end() :]
    # remainder now looks like: `/annotations/(?P<pk>...)` or
    # `/batch_exports/(?P<parent_lookup_...>)/runs/(?P<pk>...)` etc.

    # Tokenize: find all kwargs + the literal segments between them
    kwargs_found = list(_NAMED_GROUP_RE.finditer(remainder))
    if not kwargs_found:
        return None  # No pk / no further structure

    # The final named group must be a pk (not a format, not a parent_lookup)
    final = kwargs_found[-1]
    pk_kwarg = final.group(1)
    if pk_kwarg in _NON_PK_KWARGS:
        return None
    if pk_kwarg.startswith(PARENT_KWARG_PREFIX):
        return None  # Last named group is another parent lookup, not a detail URL

    # Every named group before the last must be a parent_lookup_*
    intermediate_parents: list[tuple[str, str]] = []
    cursor = 0
    for match in kwargs_found[:-1]:
        kwarg = match.group(1)
        if not kwarg.startswith(PARENT_KWARG_PREFIX):
            return None  # Unexpected structure (e.g., an inline named group)
        literal_before = remainder[cursor : match.start()]
        prefix = literal_before.strip("/")
        # Intermediate prefix can be multi-segment (e.g. `llm_analytics/datasets`)
        if not prefix:
            return None
        intermediate_parents.append((prefix, kwarg))
        cursor = match.end()

    # Resource prefix is the literal text between the last intermediate kwarg
    # (or the root if there are none) and the final pk. Can be multi-segment.
    resource_literal = remainder[cursor : final.start()]
    resource_prefix = resource_literal.strip("/")
    if not resource_prefix:
        return None

    return URLStructure(
        root=root,
        root_kwarg=root_kwarg,
        resource_prefix=resource_prefix,
        pk_kwarg=pk_kwarg,
        intermediate_parents=intermediate_parents,
    )
