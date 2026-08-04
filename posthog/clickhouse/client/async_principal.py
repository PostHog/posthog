"""Serializable references to a request principal, so an async query worker can rebuild it.

`SharedLinkUser` and `SyntheticUser` both report `id is None` by design, so a bare `user_id`
cannot carry them across the Celery boundary. `Database._fetch_sources` grants both of them a
warehouse access-control bypass, which means a worker that loses the principal falls back to
`user=None` and `_is_warehouse_table_denied` then denies every warehouse table and view.

A reference is a hint, never a grant: rebuilding re-reads the backing credential and re-applies
the same liveness predicate the request path uses, because a query can sit on the queue for up to
`process_query_task`'s ten minutes of expiry plus retries, and the credential can be revoked in
that window.
"""

from typing import TYPE_CHECKING, Any, Optional, Union

import structlog
from prometheus_client import Counter

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User
    from posthog.shared_link_user import SharedLinkUser
    from posthog.synthetic_user import SyntheticUser

    Principal = Union[User, SharedLinkUser, SyntheticUser]

logger = structlog.get_logger(__name__)

PrincipalRef = dict[str, Any]

KIND_SHARED_LINK = "shared_link"
KIND_PSAK = "psak"
KIND_TEAM_SECRET_TOKEN = "team_secret_token"

PRINCIPAL_LOST = Counter(
    "async_query_principal_lost_total",
    "Principals that could not be carried to, or rebuilt on, an async query worker. Every one of "
    "these runs the query userless, which denies all warehouse tables.",
    labelnames=["kind", "stage"],
)


def serialize_principal(user: Optional["Principal"]) -> Optional[PrincipalRef]:
    """Reference for a principal whose identity `user_id` cannot carry.

    Real users return None because their `id` already travels as `user_id`. Keeping the
    reference absent for them means the common path puts nothing extra on the wire.
    """
    # posthog.auth pulls in the DRF and model graph, and this module is reachable from
    # posthog.clickhouse.client at django.setup() time.
    from posthog.auth import (  # noqa: PLC0415 — keeps the auth graph off the startup import path
        ProjectSecretAPIKeyUser,
        TeamSecretTokenUser,
    )
    from posthog.models.user import User  # noqa: PLC0415
    from posthog.shared_link_user import SharedLinkUser  # noqa: PLC0415
    from posthog.synthetic_user import SyntheticUser  # noqa: PLC0415

    if user is None:
        return None
    if isinstance(user, SharedLinkUser):
        return {"kind": KIND_SHARED_LINK, "id": user.sharing_configuration.pk}
    if isinstance(user, ProjectSecretAPIKeyUser):
        return {"kind": KIND_PSAK, "id": user.project_secret_api_key.pk}
    if isinstance(user, TeamSecretTokenUser):
        return {"kind": KIND_TEAM_SECRET_TOKEN}
    if isinstance(user, User):
        return None

    # A SyntheticUser subclass with no branch above is a principal this module cannot re-authorize.
    # Falling through is fail-closed, but it silently reintroduces the warehouse-denial bug this
    # module exists to fix, so it has to be visible.
    if isinstance(user, SyntheticUser):
        PRINCIPAL_LOST.labels(kind=type(user).__name__, stage="serialize").inc()
        logger.warning("async_query_principal_not_serializable", principal=type(user).__name__)
    return None


def rebuild_principal(ref: Optional[PrincipalRef], team: "Team") -> Optional["Principal"]:
    """Inverse of `serialize_principal`, scoped to the team the query already runs against.

    Returns None when the reference no longer resolves, which makes the query fall back to the
    userless (fully denied) path rather than to a stale grant.
    """
    # Guard ahead of the imports so a task with no reference does no work at all.
    if not isinstance(ref, dict) or not ref:
        return None

    from posthog.auth import (  # noqa: PLC0415 — see serialize_principal
        ProjectSecretAPIKeyUser,
        TeamSecretTokenUser,
        _organization_disallows_public_sharing,
    )
    from posthog.models.project_secret_api_key import ProjectSecretAPIKey  # noqa: PLC0415
    from posthog.models.sharing_configuration import SharingConfiguration  # noqa: PLC0415
    from posthog.shared_link_user import SharedLinkUser  # noqa: PLC0415

    kind = ref.get("kind")
    principal: Optional[Principal] = None

    if kind == KIND_SHARED_LINK:
        # `tokens_active_q` is the same predicate SharingAccessTokenAuthentication uses, so expiry
        # and the rotation grace period revoke a queued query too. Checking only `enabled` here
        # would re-authorize rotated links, which stay enabled with `expires_at` in the past.
        sharing_configuration_id = _coerce_int(ref.get("id"))
        sharing_configuration = (
            SharingConfiguration.objects.filter(SharingConfiguration.tokens_active_q())
            .filter(pk=sharing_configuration_id, team_id=team.id)
            .first()
            if sharing_configuration_id is not None
            else None
        )
        if sharing_configuration is not None and not _organization_disallows_public_sharing(sharing_configuration):
            principal = SharedLinkUser(sharing_configuration)

    elif kind == KIND_PSAK:
        # Revoking a project secret API key deletes the row, so existence is the liveness check.
        # Rolling a key keeps the row, and a rolled key's queued queries are deliberately tolerated:
        # the scopes that authorize the query are re-read from the row below.
        project_secret_api_key = ProjectSecretAPIKey.objects.filter(pk=ref.get("id"), team_id=team.id).first()
        if project_secret_api_key is not None:
            # `team` is the row this query already runs against and the filter proves it is the same
            # one, so hand it over rather than let the FK lazy-load a second copy.
            project_secret_api_key.team = team
            principal = ProjectSecretAPIKeyUser(project_secret_api_key)

    elif kind == KIND_TEAM_SECRET_TOKEN:
        if team.secret_api_token:
            principal = TeamSecretTokenUser(team)

    if principal is None:
        PRINCIPAL_LOST.labels(kind=str(kind), stage="rebuild").inc()
        logger.warning("async_query_principal_rebuild_failed", kind=kind, team_id=team.id)
    return principal


def _coerce_int(value: Any) -> Optional[int]:
    """Postgres raises on a non-integer pk lookup, and an unresolvable reference must return None
    rather than burn every Celery retry on the same malformed payload."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
