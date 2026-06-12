"""
Signal handlers that keep the gateway credential cache in sync with credential and user state.

The blob is keyed by the credential hash, so a revoke / scope removal / rotation that
doesn't invalidate it leaves a stale entry for the full TTL. OAuth access also depends on
user state the token row doesn't carry (deactivation, org membership, RBAC), so those
re-project the user's OAuth credentials. Project secret keys have no user, so they
re-project only on their own save/delete and on gateway/team changes.

A pre_save fallback handles credentials loaded with hash/scope deferred (.only()/.defer()),
where post_init skips the snapshot — without it a deferred-load rotation wouldn't clear the
old hash. Wired from PostHogConfig.ready(). All handlers no-op without AI_GATEWAY_REDIS_URL,
and skip credentials that never held the gateway scope before touching Celery/Redis.
Mutations must go through .save()/.delete(); bulk_update()/.update() bypass signals.
"""

from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_init, post_save, pre_delete, pre_save

import structlog

from posthog.models.gateway import Gateway
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import SHA256_HASH_PREFIX
from posthog.storage.gateway_credential_cache import (
    GATEWAY_CREDENTIAL_REQUIRED_SCOPE,
    clear_gateway_credential,
    credential_has_gateway_scope,
)
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.tasks.gateway_credential import (
    reproject_gateway_bound_credentials_task,
    reproject_oauth_application_gateway_credentials_task,
    reproject_team_gateway_credentials_task,
    reproject_user_gateway_credentials_task,
    update_gateway_credential_cache_task,
)

logger = structlog.get_logger(__name__)

_NAMESPACE = "gateway_credential"

_LOADED_HASH_ATTR = "_fp_loaded_hash"
_LOADED_ELIGIBLE_ATTR = "_fp_loaded_eligible"
_LOADED_IS_ACTIVE_ATTR = "_fp_loaded_is_active"
_LOADED_GATEWAY_SLUG_ATTR = "_fp_loaded_gateway_slug"
_LOADED_MEMBERSHIP_LEVEL_ATTR = "_fp_loaded_membership_level"
_LOADED_APP_GATEWAY_ATTR = "_fp_loaded_app_gateway_id"
_LOADED_TEAM_API_TOKEN_ATTR = "_fp_loaded_team_api_token"

# gateway_id is legitimately None (unbound), so distinguish "not snapshotted".
_UNSET: Any = object()

_SECRET_KEY_KIND = "project_secret_api_key"
_OAUTH_KIND = "oauth_access_token"


def _secret_key_hash(instance: ProjectSecretAPIKey) -> str | None:
    return instance.secure_value


def _oauth_hash(instance: OAuthAccessToken) -> str | None:
    return f"{SHA256_HASH_PREFIX}{instance.token_checksum}" if instance.token_checksum else None


def _snapshot_secret_key(sender: type[ProjectSecretAPIKey], instance: ProjectSecretAPIKey, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    deferred = instance.get_deferred_fields()
    if "secure_value" in deferred or "scopes" in deferred:
        return
    instance.__dict__[_LOADED_HASH_ATTR] = _secret_key_hash(instance)
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = credential_has_gateway_scope(instance)


def _snapshot_oauth(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    deferred = instance.get_deferred_fields()
    if "token_checksum" in deferred or "scope" in deferred:
        return
    instance.__dict__[_LOADED_HASH_ATTR] = _oauth_hash(instance)
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = credential_has_gateway_scope(instance)


def _snapshot_user(sender: type[User], instance: User, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if "is_active" not in instance.get_deferred_fields():
        instance.__dict__[_LOADED_IS_ACTIVE_ATTR] = instance.is_active


def _capture_old_secret_key_if_deferred(
    sender: type[ProjectSecretAPIKey], instance: ProjectSecretAPIKey, **kwargs: Any
) -> None:
    # Fallback for a secret key loaded with secure_value/scopes deferred (post_init
    # skipped the snapshot): re-read the old values so a deferred-load rotation still
    # clears the old hash. No-op (no query) on the common full-load path.
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_HASH_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = ProjectSecretAPIKey.objects.filter(pk=instance.pk).values("secure_value", "scopes").first()
    if row is None:
        return
    instance.__dict__[_LOADED_HASH_ATTR] = row["secure_value"]
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = GATEWAY_CREDENTIAL_REQUIRED_SCOPE in (row["scopes"] or [])


def _capture_old_oauth_if_deferred(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_HASH_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = OAuthAccessToken.objects.filter(pk=instance.pk).values("token_checksum", "scope").first()
    if row is None:
        return
    checksum = row["token_checksum"]
    instance.__dict__[_LOADED_HASH_ATTR] = f"{SHA256_HASH_PREFIX}{checksum}" if checksum else None
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = GATEWAY_CREDENTIAL_REQUIRED_SCOPE in (row["scope"] or "").split()


def _on_credential_save(
    kind: str, instance: ProjectSecretAPIKey | OAuthAccessToken, new_hash: str | None, eligible_now: bool
) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return

    old_hash: str | None = instance.__dict__.get(_LOADED_HASH_ATTR)
    old_eligible: bool = instance.__dict__.get(_LOADED_ELIGIBLE_ATTR, False)
    instance.__dict__[_LOADED_HASH_ATTR] = new_hash
    instance.__dict__[_LOADED_ELIGIBLE_ATTR] = eligible_now

    # Skip credentials that never held the scope before touching Celery/Redis —
    # OAuth mints constantly and would otherwise flood the queue.
    if not eligible_now and not old_eligible:
        return

    def enqueue() -> None:
        try:
            # A rotated/changed hash leaves the old key live for the full TTL —
            # clear it synchronously so the stale secret stops authenticating now.
            if old_hash and old_hash != new_hash:
                clear_gateway_credential(old_hash)
            if eligible_now:
                update_gateway_credential_cache_task.delay(kind, str(instance.pk))
            elif new_hash:
                # Scope was removed: clear promptly rather than waiting for a task.
                clear_gateway_credential(new_hash)
        except Exception as e:
            HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(namespace=_NAMESPACE, operation="enqueue", result="failure").inc()
            logger.exception("Failed to enqueue gateway credential cache update", kind=kind, error=str(e))

    transaction.on_commit(enqueue)


def _update_secret_key_on_save(
    sender: type[ProjectSecretAPIKey], instance: ProjectSecretAPIKey, created: bool, **kwargs: Any
) -> None:
    # A secret key binds directly, so a rebind keeps the hash and re-projects through
    # the update task with the new slug/team — no separate app-style handler needed.
    _on_credential_save(_SECRET_KEY_KIND, instance, _secret_key_hash(instance), credential_has_gateway_scope(instance))


def _update_oauth_on_save(
    sender: type[OAuthAccessToken], instance: OAuthAccessToken, created: bool, **kwargs: Any
) -> None:
    _on_credential_save(_OAUTH_KIND, instance, _oauth_hash(instance), credential_has_gateway_scope(instance))


def _clear_secret_key_on_delete(
    sender: type[ProjectSecretAPIKey], instance: ProjectSecretAPIKey, **kwargs: Any
) -> None:
    # Clear if eligible now or at load, so an in-memory scope change before delete
    # still drops the blob promptly instead of waiting out the TTL.
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if not (credential_has_gateway_scope(instance) or instance.__dict__.get(_LOADED_ELIGIBLE_ATTR)):
        return
    cache_hash = _secret_key_hash(instance)
    if cache_hash:
        clear_gateway_credential(cache_hash)


def _clear_oauth_on_delete(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if not (credential_has_gateway_scope(instance) or instance.__dict__.get(_LOADED_ELIGIBLE_ATTR)):
        return
    cache_hash = _oauth_hash(instance)
    if cache_hash:
        clear_gateway_credential(cache_hash)


def _reproject_user_sync_then_async(user_id: int) -> None:
    # Revocation must clear synchronously so the blob can't outlive the request; the
    # credential's own revocation already does. Reproject (not a blind clear) so any
    # blobs still valid for the user's other orgs survive. Celery is the retry/warm path.
    def _invalidate() -> None:
        try:
            reproject_user_gateway_credentials_task(user_id)
        except Exception as e:
            logger.exception("Synchronous gateway credential reprojection failed", user_id=user_id, error=str(e))
        reproject_user_gateway_credentials_task.delay(user_id)

    transaction.on_commit(_invalidate)


def _reproject_user_on_save(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    # Only OAuth carries a user. Deactivation must clear it (the token row doesn't
    # change on is_active flips); reactivation re-grants.
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_is_active = instance.__dict__.get(_LOADED_IS_ACTIVE_ATTR)
    instance.__dict__[_LOADED_IS_ACTIVE_ATTR] = instance.is_active
    if old_is_active is None or old_is_active == instance.is_active:
        return

    _reproject_user_sync_then_async(instance.pk)


def _reproject_on_membership_delete(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any
) -> None:
    # Losing membership revokes OAuth access without touching the token, so reproject
    # the user — the policy now fails closed for a non-member and clears the blob.
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    _reproject_user_sync_then_async(instance.user_id)


def _snapshot_oauth_application(sender: type[OAuthApplication], instance: OAuthApplication, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if "gateway" not in instance.get_deferred_fields():
        instance.__dict__[_LOADED_APP_GATEWAY_ATTR] = instance.gateway_id


def _capture_old_app_gateway_if_deferred(
    sender: type[OAuthApplication], instance: OAuthApplication, **kwargs: Any
) -> None:
    # Fallback for an app loaded with `gateway` deferred (post_init skipped the
    # snapshot): re-read the old gateway before the UPDATE so a rebind still
    # reprojects. No-op (no query) on the common full-load path.
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_APP_GATEWAY_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = OAuthApplication.objects.filter(pk=instance.pk).values("gateway_id").first()
    if row is not None:
        instance.__dict__[_LOADED_APP_GATEWAY_ATTR] = row["gateway_id"]


def _reproject_oauth_application_on_save(
    sender: type[OAuthApplication], instance: OAuthApplication, created: bool, **kwargs: Any
) -> None:
    # The binding lives on the application, not the token, so a rebind doesn't fire a
    # token save. Reproject the app's tokens so they pick up the new slug/team (or clear).
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_gateway_id = instance.__dict__.get(_LOADED_APP_GATEWAY_ATTR, _UNSET)
    instance.__dict__[_LOADED_APP_GATEWAY_ATTR] = instance.gateway_id
    if old_gateway_id is _UNSET or old_gateway_id == instance.gateway_id:
        return

    application_id = str(instance.pk)
    transaction.on_commit(lambda: reproject_oauth_application_gateway_credentials_task.delay(application_id))


def _snapshot_team(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if "api_token" not in instance.get_deferred_fields():
        instance.__dict__[_LOADED_TEAM_API_TOKEN_ATTR] = instance.api_token


def _capture_old_team_token_if_deferred(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_TEAM_API_TOKEN_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = Team.objects.filter(pk=instance.pk).values("api_token").first()
    if row is not None:
        instance.__dict__[_LOADED_TEAM_API_TOKEN_ATTR] = row["api_token"]


def _reproject_team_on_api_token_change(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    # project_token in the blob is the team's api_token; a rotation leaves every
    # gateway credential blob on this team's gateways carrying the stale token.
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_token = instance.__dict__.get(_LOADED_TEAM_API_TOKEN_ATTR)
    instance.__dict__[_LOADED_TEAM_API_TOKEN_ATTR] = instance.api_token
    if not old_token or old_token == instance.api_token:
        return

    team_id = instance.pk
    transaction.on_commit(lambda: reproject_team_gateway_credentials_task.delay(team_id))


def _snapshot_membership(sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if "level" not in instance.get_deferred_fields():
        instance.__dict__[_LOADED_MEMBERSHIP_LEVEL_ATTR] = instance.level


def _capture_old_membership_level_if_deferred(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any
) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_MEMBERSHIP_LEVEL_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = OrganizationMembership.objects.filter(pk=instance.pk).values("level").first()
    if row is not None:
        instance.__dict__[_LOADED_MEMBERSHIP_LEVEL_ATTR] = row["level"]


def _reproject_on_membership_save(
    sender: type[OrganizationMembership], instance: OrganizationMembership, created: bool, **kwargs: Any
) -> None:
    # level feeds the OAuth org-admin RBAC bypass, so a change can flip the policy.
    # Creation grants nothing on its own; deletion is handled separately.
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_level = instance.__dict__.get(_LOADED_MEMBERSHIP_LEVEL_ATTR)
    instance.__dict__[_LOADED_MEMBERSHIP_LEVEL_ATTR] = instance.level
    if old_level is None or old_level == instance.level:
        return

    user_id = instance.user_id
    transaction.on_commit(lambda: reproject_user_gateway_credentials_task.delay(user_id))


def _snapshot_gateway(sender: type[Gateway], instance: Gateway, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if "slug" not in instance.get_deferred_fields():
        instance.__dict__[_LOADED_GATEWAY_SLUG_ATTR] = instance.slug


def _capture_old_gateway_slug_if_deferred(sender: type[Gateway], instance: Gateway, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_GATEWAY_SLUG_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = Gateway.all_teams.filter(pk=instance.pk).values("slug").first()
    if row is not None:
        instance.__dict__[_LOADED_GATEWAY_SLUG_ATTR] = row["slug"]


def _reproject_gateway_on_save(sender: type[Gateway], instance: Gateway, created: bool, **kwargs: Any) -> None:
    # The slug is the attribution value; on change, re-project every bound
    # credential so its blob carries the new slug. Binding/unbinding a credential
    # fires that credential's own save signal, so it's covered elsewhere.
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_slug = instance.__dict__.get(_LOADED_GATEWAY_SLUG_ATTR)
    instance.__dict__[_LOADED_GATEWAY_SLUG_ATTR] = instance.slug
    if old_slug is None or old_slug == instance.slug:
        return

    gateway_id = str(instance.pk)
    transaction.on_commit(lambda: reproject_gateway_bound_credentials_task.delay(gateway_id))


def _bound_credential_hashes(gateway_id: UUID | str) -> list[str]:
    """Cache-key hashes of the gateway-scoped credentials bound to a gateway."""
    hashes = [
        secure_value
        for secure_value in ProjectSecretAPIKey.objects.filter(
            gateway_id=gateway_id, scopes__contains=[GATEWAY_CREDENTIAL_REQUIRED_SCOPE]
        ).values_list("secure_value", flat=True)
        if secure_value
    ]
    hashes += [
        f"{SHA256_HASH_PREFIX}{checksum}"
        for checksum in OAuthAccessToken.objects.filter(
            application__gateway_id=gateway_id, scope__iregex=r"(^|\s)llm_gateway:read(\s|$)"
        ).values_list("token_checksum", flat=True)
        if checksum
    ]
    return hashes


def _clear_gateway_on_delete(sender: type[Gateway], instance: Gateway, **kwargs: Any) -> None:
    # gateway FK is PROTECT, so a gateway with bound credentials can't be deleted;
    # this is a safety net for the drained-then-deleted case. on_commit only fires on
    # a successful delete, so a PROTECT-aborted delete never wrongly clears a blob.
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    hashes = _bound_credential_hashes(instance.pk)
    if hashes:
        transaction.on_commit(lambda: _clear_policy_hashes(hashes))


def _clear_policy_hashes(hashes: list[str]) -> None:
    for hash_key in hashes:
        clear_gateway_credential(hash_key)


def _reproject_on_access_control_change(sender: type, instance: Any, **kwargs: Any) -> None:
    # A project AC flips the OAuth RBAC check; the projection keys ACs by team_id, so
    # reproject the team's credentials and a revocation clears promptly.
    if not settings.AI_GATEWAY_REDIS_URL or instance.resource != "project" or instance.team_id is None:
        return
    team_id = instance.team_id
    transaction.on_commit(lambda: reproject_team_gateway_credentials_task.delay(team_id))


def _reproject_on_role_membership_change(sender: type, instance: Any, **kwargs: Any) -> None:
    # Role membership feeds role-scoped ACs, so a change can flip project access with no
    # AccessControl row changing. Per-user, so clear synchronously like the other
    # user-scoped revocations (unlike the team-wide access-control handler).
    if not settings.AI_GATEWAY_REDIS_URL or instance.user_id is None:
        return
    _reproject_user_sync_then_async(instance.user_id)


def connect_signal_handlers() -> None:
    post_init.connect(_snapshot_secret_key, sender=ProjectSecretAPIKey)
    pre_save.connect(_capture_old_secret_key_if_deferred, sender=ProjectSecretAPIKey)
    post_save.connect(_update_secret_key_on_save, sender=ProjectSecretAPIKey)
    pre_delete.connect(_clear_secret_key_on_delete, sender=ProjectSecretAPIKey)

    post_init.connect(_snapshot_oauth, sender=OAuthAccessToken)
    pre_save.connect(_capture_old_oauth_if_deferred, sender=OAuthAccessToken)
    post_save.connect(_update_oauth_on_save, sender=OAuthAccessToken)
    pre_delete.connect(_clear_oauth_on_delete, sender=OAuthAccessToken)

    post_init.connect(_snapshot_oauth_application, sender=OAuthApplication)
    pre_save.connect(_capture_old_app_gateway_if_deferred, sender=OAuthApplication)
    post_save.connect(_reproject_oauth_application_on_save, sender=OAuthApplication)

    post_init.connect(_snapshot_team, sender=Team)
    pre_save.connect(_capture_old_team_token_if_deferred, sender=Team)
    post_save.connect(_reproject_team_on_api_token_change, sender=Team)

    post_init.connect(_snapshot_user, sender=User)
    post_save.connect(_reproject_user_on_save, sender=User)

    post_init.connect(_snapshot_membership, sender=OrganizationMembership)
    pre_save.connect(_capture_old_membership_level_if_deferred, sender=OrganizationMembership)
    post_save.connect(_reproject_on_membership_save, sender=OrganizationMembership)
    post_delete.connect(_reproject_on_membership_delete, sender=OrganizationMembership)

    post_init.connect(_snapshot_gateway, sender=Gateway)
    pre_save.connect(_capture_old_gateway_slug_if_deferred, sender=Gateway)
    post_save.connect(_reproject_gateway_on_save, sender=Gateway)
    pre_delete.connect(_clear_gateway_on_delete, sender=Gateway)

    # Project access controls live in ee, which isn't installed in FOSS. Connect
    # only when available; the projection's RBAC check default-allows there anyway.
    try:
        from ee.models.rbac.access_control import AccessControl
        from ee.models.rbac.role import RoleMembership

        post_save.connect(_reproject_on_access_control_change, sender=AccessControl)
        post_delete.connect(_reproject_on_access_control_change, sender=AccessControl)
        post_save.connect(_reproject_on_role_membership_change, sender=RoleMembership)
        post_delete.connect(_reproject_on_role_membership_change, sender=RoleMembership)
    except ImportError:
        pass
