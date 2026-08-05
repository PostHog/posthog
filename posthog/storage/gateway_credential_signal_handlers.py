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

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_delete, post_init, post_save, pre_delete, pre_save

import structlog

from posthog.models.oauth import OAuthAccessToken
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

# The gateway-credential task functions are imported lazily inside the handlers
# below: this module is wired at django.setup(), and importing posthog.tasks.*
# eagerly loads every task module (celery autoimport), dragging posthog.schema /
# posthog.hogql onto the startup path of every process. See django-startup-time.

logger = structlog.get_logger(__name__)

_CACHE_NAME = "gateway_credential"

_LOADED_HASH_ATTR = "_fp_loaded_hash"
_LOADED_ELIGIBLE_ATTR = "_fp_loaded_eligible"
_LOADED_IS_ACTIVE_ATTR = "_fp_loaded_is_active"
_LOADED_MEMBERSHIP_LEVEL_ATTR = "_fp_loaded_membership_level"
_LOADED_TEAM_API_TOKEN_ATTR = "_fp_loaded_team_api_token"
_LOADED_TEAM_OVERSPEND_ATTR = "_fp_loaded_team_overspend_allowance"

# Distinguishes "no snapshot captured" from a captured null allowance (null is a valid value).
_UNSET = object()

_SECRET_KEY_KIND = "project_secret_api_key"
_OAUTH_KIND = "oauth_access_token"


def _best_effort_clear(cache_hash: str) -> None:
    # These direct clears fire from signals running inside the DB write itself
    # (pre_delete) or its post-commit hook. A transient Redis outage must not
    # 500 the underlying save/delete — the blob's TTL (and the async reprojection
    # paths) are the durable backstop. Best-effort: log and move on.
    try:
        clear_gateway_credential(cache_hash)
    except Exception as e:
        logger.warning("gateway_credential clear failed; relying on TTL backstop", error=str(e))


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


def _capture_old_user_is_active_if_deferred(sender: type[User], instance: User, **kwargs: Any) -> None:
    # Fallback for a user loaded with is_active deferred (.only()/.defer()): re-read the
    # old value so a deferred-load deactivation still clears the blob. No query on the
    # common full-load path, where post_init already snapshotted.
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_IS_ACTIVE_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = User.objects.filter(pk=instance.pk).values("is_active").first()
    if row is not None:
        instance.__dict__[_LOADED_IS_ACTIVE_ATTR] = row["is_active"]


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
        from posthog.tasks.gateway_credential import update_gateway_credential_cache_task  # noqa: PLC0415

        try:
            # A rotated/changed hash leaves the old key live for the full TTL —
            # clear it synchronously so the stale secret stops authenticating now.
            if old_hash and old_hash != new_hash:
                _best_effort_clear(old_hash)
            if eligible_now:
                update_gateway_credential_cache_task.delay(kind, str(instance.pk))
            elif new_hash:
                # Scope was removed: clear promptly rather than waiting for a task.
                _best_effort_clear(new_hash)
        except Exception as e:
            HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
                namespace="team_metadata", cache_name=_CACHE_NAME, operation="enqueue", result="failure"
            ).inc()
            logger.exception("Failed to enqueue gateway credential cache update", kind=kind, error=str(e))
            # A sync clear/enqueue failed (e.g. transient Redis) — queue the task so a
            # revoke self-heals in queue-time instead of waiting out the blob TTL. The
            # task re-projects the current credential: writes if eligible, clears if not.
            update_gateway_credential_cache_task.delay(kind, str(instance.pk))

    transaction.on_commit(enqueue)


def _update_secret_key_on_save(
    sender: type[ProjectSecretAPIKey], instance: ProjectSecretAPIKey, created: bool, **kwargs: Any
) -> None:
    # A scope/team change keeps the hash and re-projects through the update task,
    # which resolves the key's team gateway afresh.
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
        _best_effort_clear(cache_hash)


def _clear_oauth_on_delete(sender: type[OAuthAccessToken], instance: OAuthAccessToken, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    if not (credential_has_gateway_scope(instance) or instance.__dict__.get(_LOADED_ELIGIBLE_ATTR)):
        return
    cache_hash = _oauth_hash(instance)
    if cache_hash:
        _best_effort_clear(cache_hash)


def _reproject_user_sync_then_async(user_id: int) -> None:
    # Revocation must clear synchronously so the blob can't outlive the request; the
    # credential's own revocation already does. Reproject (not a blind clear) so any
    # blobs still valid for the user's other orgs survive. Celery is the retry/warm path.
    def _invalidate() -> None:
        from posthog.tasks.gateway_credential import reproject_user_gateway_credentials_task  # noqa: PLC0415

        try:
            reproject_user_gateway_credentials_task(user_id)
        except Exception as e:
            logger.exception("Synchronous gateway credential reprojection failed", user_id=user_id, error=str(e))
            # Sync clear failed (e.g. transient Redis) — queue an async retry so the
            # blob can't outlive the TTL. No retry needed when the sync run succeeded.
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


def _capture_old_team_fields_if_deferred(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    # Sole snapshot source for Team: no post_init handler, since these rows are loaded
    # far more often than saved — one query per save beats a snapshot on every load.
    if not settings.AI_GATEWAY_REDIS_URL or _LOADED_TEAM_API_TOKEN_ATTR in instance.__dict__:
        return
    if not instance.pk or instance._state.adding:
        return
    row = Team.objects.filter(pk=instance.pk).values("api_token", "llm_gateway_overspend_allowance_usd").first()
    if row is not None:
        instance.__dict__[_LOADED_TEAM_API_TOKEN_ATTR] = row["api_token"]
        instance.__dict__[_LOADED_TEAM_OVERSPEND_ATTR] = row["llm_gateway_overspend_allowance_usd"]


def _reproject_team_on_change(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    # api_token (project_token) and overspend allowance both feed every credential blob on
    # this team; a change to either leaves them stale, so re-project.
    if not settings.AI_GATEWAY_REDIS_URL or created:
        return
    old_token = instance.__dict__.get(_LOADED_TEAM_API_TOKEN_ATTR)
    old_allowance = instance.__dict__.get(_LOADED_TEAM_OVERSPEND_ATTR, _UNSET)
    instance.__dict__[_LOADED_TEAM_API_TOKEN_ATTR] = instance.api_token
    instance.__dict__[_LOADED_TEAM_OVERSPEND_ATTR] = instance.llm_gateway_overspend_allowance_usd

    token_changed = bool(old_token) and old_token != instance.api_token
    allowance_changed = old_allowance is not _UNSET and old_allowance != instance.llm_gateway_overspend_allowance_usd
    if not token_changed and not allowance_changed:
        return

    from posthog.tasks.gateway_credential import reproject_team_gateway_credentials_task  # noqa: PLC0415

    team_id = instance.pk
    transaction.on_commit(lambda: reproject_team_gateway_credentials_task.delay(team_id))


def _capture_old_membership_level_if_deferred(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any
) -> None:
    # Sole snapshot source for OrganizationMembership: no post_init handler, since these
    # rows are loaded far more often than saved — one query per save beats a snapshot on
    # every load.
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

    from posthog.tasks.gateway_credential import reproject_user_gateway_credentials_task  # noqa: PLC0415

    user_id = instance.user_id
    transaction.on_commit(lambda: reproject_user_gateway_credentials_task.delay(user_id))


def _reproject_on_access_control_change(sender: type, instance: Any, **kwargs: Any) -> None:
    # A project AC flips the OAuth RBAC check; the projection keys ACs by team_id, so
    # reproject the team's credentials and a revocation clears promptly.
    if not settings.AI_GATEWAY_REDIS_URL or instance.resource != "project" or instance.team_id is None:
        return
    from posthog.tasks.gateway_credential import reproject_team_gateway_credentials_task  # noqa: PLC0415

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

    # Team / OrganizationMembership: pre_save fallback only (no post_init). These rows
    # are read far more than written, so paying one query per save beats snapshotting
    # every load.
    pre_save.connect(_capture_old_team_fields_if_deferred, sender=Team)
    post_save.connect(_reproject_team_on_change, sender=Team)

    post_init.connect(_snapshot_user, sender=User)
    pre_save.connect(_capture_old_user_is_active_if_deferred, sender=User)
    post_save.connect(_reproject_user_on_save, sender=User)

    pre_save.connect(_capture_old_membership_level_if_deferred, sender=OrganizationMembership)
    post_save.connect(_reproject_on_membership_save, sender=OrganizationMembership)
    post_delete.connect(_reproject_on_membership_delete, sender=OrganizationMembership)

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
