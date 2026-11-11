"""Every API scope has a type in the authorization SDK.

The shared permission check names a view's scope as an SDK `ResourceType`. A scope without a type
fails that check with a 500 on every route that declares the scope. The scope list and the SDK enum
live in different trees, so this check runs here, on every backend pull request.

To clear a violation, add a member for each new scope to `ResourceType` in
`products/authorization/backend/facade/enums.py`.

    pytest posthog/test/repo_invariants/test_api_scopes_have_resource_types.py
"""

from posthog.scopes import API_SCOPE_OBJECTS

from products.authorization.backend.facade.enums import ResourceType


def test_every_api_scope_has_a_resource_type() -> None:
    missing = set(API_SCOPE_OBJECTS) - {resource_type.value for resource_type in ResourceType}
    assert missing == set(), (
        f"Add a ResourceType to products/authorization/backend/facade/enums.py for: {sorted(missing)}"
    )
