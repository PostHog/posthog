"""Every exposed API scope object has exactly one ScopeDoc.

Scope pickers, `/oauth/scopes/` and the scope reference on posthog.com show a scope's name,
description and docs link from its ScopeDoc, so an exposed object without one would appear unexplained.

To clear a failure, add a `ScopeDoc` for the object to `SCOPE_DOCS` in the owning product's
`backend/scopes.py`, or to `CORE_SCOPE_DOCS` in `posthog/scope_docs.py` for a core scope, then run
`hogli build:projections`. An object that no picker should offer goes in
`SCOPE_OBJECTS_OMITTED_FROM_PICKERS` in `posthog/scopes.py` instead.

    pytest posthog/test/repo_invariants/test_scope_docs.py
"""

from posthog.products import load_product_modules
from posthog.scope_docs import get_scope_docs
from posthog.scope_docs_projection import product_scope_module_names
from posthog.scopes import EXPOSED_SCOPE_OBJECTS


def test_every_exposed_scope_object_has_one_scope_doc() -> None:
    declared = set(get_scope_docs())
    exposed = set(EXPOSED_SCOPE_OBJECTS)

    assert sorted(exposed - declared) == [], "exposed scope objects without a ScopeDoc"
    assert sorted(declared - exposed) == [], "ScopeDocs for scope objects no picker exposes"


def test_projection_and_app_find_the_same_scope_modules() -> None:
    installed = sorted(module.__name__ for module in load_product_modules("scopes"))

    assert product_scope_module_names() == installed
