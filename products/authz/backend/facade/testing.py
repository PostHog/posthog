from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

from unittest.mock import MagicMock, patch

from openfga_sdk.client.models import ClientCheckRequest, ClientListObjectsRequest

from posthog.models import SharingConfiguration

from ..logic.synchronization import OrganizationProjection, Relationship


def share_relationships(principal: str) -> set[Relationship]:
    if not principal.startswith("share_link:"):
        return set()
    organization_id = (
        # nosemgrep: idor-lookup-without-team -- the test double resolves the principal's tenant before projecting grants
        SharingConfiguration.objects.filter(pk=int(principal.removeprefix("share_link:")))
        .values_list("team__organization_id", flat=True)
        .first()
    )
    return OrganizationProjection(organization_id).build() if organization_id is not None else set()


@contextmanager
def mock_share_link_authorization() -> Iterator[MagicMock]:
    client = MagicMock()

    def check(requests: list[ClientCheckRequest], options: object) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                allowed=request.relation == "can_view"
                and Relationship(user=request.user, relation="shared_viewer", object=request.object)
                in share_relationships(request.user),
                error=None,
            )
            for request in requests
        ]

    def list_objects(request: ClientListObjectsRequest, options: object) -> MagicMock:
        stream = MagicMock()
        stream.__iter__.return_value = iter(
            SimpleNamespace(object=relationship.object)
            for relationship in share_relationships(request.user)
            if request.relation == "can_view"
            and relationship.relation == "shared_viewer"
            and relationship.user == request.user
            and relationship.object.startswith(f"{request.type}:")
        )
        return stream

    client.client_batch_check.side_effect = check
    client.streamed_list_objects.side_effect = list_objects
    with (
        patch("products.authz.backend.logic.authorization.ready_state", return_value=b"ready:test"),
        patch(
            "products.authz.backend.logic.authorization.pooled_openfga_client", side_effect=lambda: nullcontext(client)
        ),
    ):
        yield client
