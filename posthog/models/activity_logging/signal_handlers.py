import sys
import time
import dataclasses
from collections.abc import Callable
from datetime import timedelta
from typing import Literal, Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.core.signing import TimestampSigner
from django.db.models.signals import pre_delete
from django.dispatch import receiver
from django.http import HttpRequest

import structlog
from loginas import settings as la_settings
from prometheus_client import Counter

from posthog.caching.login_device_cache import check_and_cache_login_device
from posthog.constants import AUTH_BACKEND_DISPLAY_NAMES
from posthog.exceptions_capture import capture_exception
from posthog.geoip import get_geoip_properties
from posthog.helpers.impersonation import get_original_user_from_session, is_impersonated
from posthog.models import Organization, PersonalAPIKey, Tag, TaggedItem
from posthog.models.activity_logging.activity_log import (
    ActivityContextBase,
    ActivityScope,
    Change,
    Detail,
    LogActivityEntry,
    bulk_log_activity,
    changes_between,
    log_activity,
)
from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated
from posthog.models.activity_logging.personal_api_key_utils import (
    log_personal_api_key_activity,
    log_personal_api_key_scope_change,
)
from posthog.models.activity_logging.project_secret_api_key_utils import log_project_secret_api_key_activity
from posthog.models.activity_logging.tag_utils import get_tagged_item_related_object_info
from posthog.models.activity_logging.utils import activity_storage
from posthog.models.oauth import OAuthApplication
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.project_secret_api_key import ProjectSecretAPIKey
from posthog.models.signals import model_activity_signal, mutable_receiver
from posthog.models.user import User
from posthog.session.models import Session
from posthog.utils import get_ip_address, get_short_user_agent

from products.experiments.backend.models.experiment import (
    ExperimentHoldout,
    ExperimentSavedMetric,
    ExperimentToSavedMetric,
)

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UserLoginContext(ActivityContextBase):
    login_method: str
    ip_address: str
    user_agent: str
    reauth: bool


@dataclasses.dataclass(frozen=True)
class UserLogoutContext(ActivityContextBase):
    ip_address: str
    user_agent: str


def _get_logout_user_context(user, request):
    """Determine the correct user context and attribution for logout activity logging."""
    was_impersonated = is_impersonated(request)
    log_user = user
    item_id = str(user.id)

    if was_impersonated and hasattr(request, "session") and request.session:
        admin_user = get_original_user_from_session(request)
        if admin_user:
            log_user = admin_user
            item_id = str(user.id)

    return was_impersonated, log_user, item_id


def _detect_impersonation_for_login(user, request):
    """Detect impersonation context for login events using stack inspection and session state."""
    has_impersonation_session = (
        hasattr(request, "session") and request.session and la_settings.USER_SESSION_FLAG in request.session
    )

    # Walk raw frames instead of inspect.stack(): the latter resolves source context for
    # every frame (linecache + sys.modules scans), which costs ~200ms per login.
    frame = sys._getframe().f_back
    while frame is not None:
        if "loginas" in frame.f_code.co_filename:
            try:
                if "original_user_pk" in frame.f_locals:
                    User = get_user_model()
                    original_user_pk = frame.f_locals["original_user_pk"]
                    admin_user = User.objects.get(pk=original_user_pk)
                    return True, admin_user, str(user.id), "impersonation"
            except Exception:
                pass

            return True, user, str(user.id), "impersonation"
        frame = frame.f_back

    if has_impersonation_session:
        try:
            original_user_pk = TimestampSigner().unsign(
                request.session.get(la_settings.USER_SESSION_FLAG),
                max_age=timedelta(days=la_settings.USER_SESSION_DAYS_TIMESTAMP),
            )
            User = get_user_model()
            admin_user = User.objects.get(pk=original_user_pk)
            return True, admin_user, str(user.id), "impersonation"
        except Exception:
            pass

    return False, user, str(user.id), "normal"


def _determine_login_method(request, was_impersonated):
    """Determine the login method based on the request and impersonation status."""

    if was_impersonated:
        return "Impersonation"

    backend = request.session.get("_auth_user_backend", "django.contrib.auth.backends.ModelBackend")
    login_method = AUTH_BACKEND_DISPLAY_NAMES.get(backend, "Unknown")

    return login_method


@receiver(user_logged_in)
def log_user_login_activity(sender, user, request: HttpRequest, **kwargs):  # noqa: ARG001
    try:
        was_impersonated, log_user, item_id, _ = _detect_impersonation_for_login(user, request)
        ip_address = get_ip_address(request)
        user_agent = get_short_user_agent(request)
        reauth = request.session.get("reauth") == "true"

        organization_id = user.current_organization_id

        if organization_id is None:
            logger.info("Skipping login activity log - user has no organization", user_id=user.id)
            return

        log_activity(
            organization_id=organization_id,
            team_id=None,
            user=log_user,
            item_id=item_id,
            scope="User",
            activity="logged_in",
            detail=Detail(
                name=user.email,
                changes=[],
                context=UserLoginContext(
                    login_method=_determine_login_method(request, was_impersonated),
                    ip_address=ip_address,
                    user_agent=user_agent,
                    reauth=reauth,
                ),
            ),
            was_impersonated=was_impersonated,
        )
    except Exception as e:
        logger.exception("Failed to log user login activity", user_id=user.id, error=e)
        capture_exception(e)


@receiver(user_logged_out)
def log_user_logout_activity(sender, user, request: HttpRequest, **kwargs):  # noqa: ARG001
    if not user:
        return

    try:
        was_impersonated, log_user, item_id = _get_logout_user_context(user, request)

        ip_address = get_ip_address(request)
        user_agent = get_short_user_agent(request)

        organization_id = user.current_organization_id

        if organization_id is None:
            logger.info("Skipping logout activity log - user has no organization", user_id=user.id)
            return

        log_activity(
            organization_id=organization_id,
            team_id=None,
            user=log_user,
            item_id=item_id,
            scope="User",
            activity="logged_out",
            detail=Detail(
                name=user.email,
                changes=[],
                context=UserLogoutContext(
                    ip_address=ip_address,
                    user_agent=user_agent,
                ),
            ),
            was_impersonated=was_impersonated,
        )
    except Exception as e:
        logger.exception("Failed to log user logout activity", user_id=user.id, error=e)
        capture_exception(e)


@mutable_receiver(model_activity_signal, sender=User)
def log_user_change_activity(
    sender: type[User],
    scope: ActivityScope,
    before_update: User | None,
    after_update: User | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs,
) -> None:
    """
    Handle User model activity signals for create and update events.

    Unlike other models that log to a single organization, User activity is logged to ALL
    organizations the user belongs to.
    """
    try:
        target_user = after_update or before_update

        if not target_user:
            return

        memberships = list(target_user.organization_memberships.all())

        if not memberships:
            logger.info(
                "Skipping user activity log - user has no organization memberships",
                user_id=target_user.id,
                activity=activity,
            )
            return

        changes = changes_between(scope, previous=before_update, current=after_update)
        user_name = f"{target_user.first_name} {target_user.last_name}".strip() or target_user.email

        log_entries: list[LogActivityEntry] = []
        for membership in memberships:
            log_entries.append(
                LogActivityEntry(
                    organization_id=membership.organization_id,
                    team_id=None,
                    user=user,
                    item_id=target_user.id,
                    scope=scope,
                    activity=activity,
                    detail=Detail(
                        changes=changes,
                        name=user_name,
                    ),
                    was_impersonated=was_impersonated,
                )
            )

        if log_entries:
            bulk_log_activity(log_entries)

    except Exception as e:
        logger.exception(
            "Failed to log user activity",
            user_id=target_user.id if target_user else None,
            activity=activity,
            error=e,
        )
        capture_exception(e)


@dataclasses.dataclass(frozen=True)
class OrganizationDomainContext(ActivityContextBase):
    organization_id: str
    organization_name: str
    domain: str


@mutable_receiver(model_activity_signal, sender=OrganizationDomain)
def handle_organization_domain_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    domain_instance = after_update or before_update

    if not domain_instance:
        return

    context = OrganizationDomainContext(
        organization_id=str(domain_instance.organization_id),
        organization_name=domain_instance.organization.name,
        domain=domain_instance.domain,
    )

    if activity == "created":
        detail_name = f"Domain {domain_instance.domain} added to {domain_instance.organization.name}"
    elif activity == "deleted":
        detail_name = f"Domain {domain_instance.domain} removed from {domain_instance.organization.name}"
    else:
        detail_name = f"Domain {domain_instance.domain} updated in {domain_instance.organization.name}"

    log_activity(
        organization_id=domain_instance.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=domain_instance.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )


@mutable_receiver(model_activity_signal, sender=ExperimentSavedMetric)
def handle_experiment_saved_metric_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope="Experiment",  # log under Experiment scope so it appears in experiment activity log
        activity=activity,
        detail=Detail(
            # need to use ExperimentSavedMetric here for field exclusions..
            changes=changes_between("ExperimentSavedMetric", previous=before_update, current=after_update),
            name=after_update.name,
            type="shared_metric",
        ),
    )


@receiver(pre_delete, sender=ExperimentSavedMetric)
def handle_experiment_saved_metric_delete(sender, instance, **kwargs):
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=activity_storage.get_user() or getattr(instance, "last_modified_by", instance.created_by),
        was_impersonated=activity_storage.get_was_impersonated(),
        item_id=instance.id,
        scope="Experiment",  # log under Experiment scope so it appears in experiment activity log
        activity="deleted",
        detail=Detail(name=instance.name, type="shared_metric"),
    )


@mutable_receiver(model_activity_signal, sender=ExperimentHoldout)
def handle_experiment_holdout_change(
    sender, scope, before_update, after_update, activity, user=None, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=user or after_update.created_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope="Experiment",  # log under Experiment scope so it appears in experiment activity log
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
            type="holdout",
        ),
    )


@receiver(pre_delete, sender=ExperimentHoldout)
def handle_experiment_holdout_delete(sender, instance, **kwargs):
    log_activity(
        organization_id=instance.team.organization_id,
        team_id=instance.team_id,
        user=activity_storage.get_user() or getattr(instance, "last_modified_by", instance.created_by),
        was_impersonated=activity_storage.get_was_impersonated(),
        item_id=instance.id,
        scope="Experiment",
        activity="deleted",
        detail=Detail(name=instance.name, type="holdout"),
    )


@dataclasses.dataclass(frozen=True)
class OAuthApplicationScopesContext(ActivityContextBase):
    client_id: str
    is_cimd_client: bool
    is_dcr_client: bool
    is_first_party: bool


@mutable_receiver(model_activity_signal, sender=OAuthApplication)
def handle_oauth_application_scopes_change(
    sender: type[OAuthApplication],
    scope: ActivityScope,
    before_update: OAuthApplication | None,
    after_update: OAuthApplication | None,
    activity: str,
    user: User | None,
    was_impersonated: bool = False,
    **kwargs,
) -> None:
    application = after_update or before_update
    if application is None:
        return

    if activity == "created":
        if not application.scopes:
            return
        changes = [Change(type=scope, action="created", field="scopes", after=list(application.scopes or []))]
    else:
        if before_update is None or after_update is None:
            return
        # `scopes` is an ordered ArrayField but semantically a set (a permission ceiling),
        # so a pure reorder is not an auditable change.
        if set(before_update.scopes or []) == set(after_update.scopes or []):
            return
        # Only the scope ceiling is audited for OAuth apps; other fields changed in the
        # same save are deliberately left out of the entry.
        changes = [
            change
            for change in changes_between(scope, previous=before_update, current=after_update)
            if change.field == "scopes"
        ]
        if not changes:
            return

    organization_id = application.organization_id or (user.current_organization_id if user else None)
    if organization_id is None:
        # ActivityLog rows must carry an organization or team. Apps registered anonymously
        # (e.g. DCR) have neither until they are linked to an organization — and without an
        # organization there is nobody who could view the entry anyway.
        logger.warning(
            "oauth_application_scopes_change_not_logged",
            application_id=str(application.pk),
            activity=activity,
        )
        return

    log_activity(
        organization_id=organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=application.pk,
        scope=scope,
        activity=activity,
        detail=Detail(
            name=application.name,
            changes=changes,
            context=OAuthApplicationScopesContext(
                client_id=application.client_id,
                is_cimd_client=application.is_cimd_client,
                is_dcr_client=application.is_dcr_client,
                is_first_party=application.is_first_party,
            ),
        ),
    )


@mutable_receiver(model_activity_signal, sender=ExperimentToSavedMetric)
def handle_experiment_to_saved_metric_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    instance = after_update or before_update
    if not instance:
        return

    log_activity(
        organization_id=instance.experiment.team.organization_id,
        team_id=instance.experiment.team_id,
        user=user or activity_storage.get_user(),
        was_impersonated=was_impersonated or activity_storage.get_was_impersonated(),
        item_id=instance.experiment_id,
        # Stored under the public Experiment scope so it shows up in the experiment
        # activity log feed. The describer arm on `type="saved_metric_config"`
        # renders the row.
        scope="Experiment",
        activity=activity,
        detail=Detail(
            # `"ExperimentToSavedMetric"` is an InternalActivityScope key used only for
            # field_exclusions / changes_between — never written to ActivityLog.scope.
            changes=changes_between("ExperimentToSavedMetric", previous=before_update, current=after_update),
            name=instance.saved_metric.name,
            type="saved_metric_config",
        ),
    )


# --- Receivers relocated from posthog.api viewset modules ---------------------------------
# These used to live next to their viewsets and wired in as an import side effect of the
# eager API router. With the lazy router, AppConfig.ready() imports this module instead, so
# they connect in every process — importing a 400+ line DRF module at setup just for its
# receivers proved rot-prone (the module gains heavy imports, setup silently inherits them).


@dataclasses.dataclass(frozen=True)
class TagContext(ActivityContextBase):
    team_id: int
    name: str


@dataclasses.dataclass(frozen=True)
class TaggedItemContext(ActivityContextBase):
    tag_name: str
    tag_id: str
    team_id: int
    related_object_type: Optional[str] = None
    related_object_id: Optional[str] = None
    related_object_name: Optional[str] = None


@mutable_receiver(model_activity_signal, sender=Tag)
def handle_tag_change(sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs):
    context = TagContext(
        team_id=after_update.team_id,
        name=after_update.name,
    )

    log_activity(
        organization_id=after_update.team.organization_id if after_update.team else None,
        team_id=after_update.team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
            context=context,
        ),
    )


@dataclasses.dataclass(frozen=True)
class RelatedObjectActivityLogger:
    """How to mirror a TaggedItem activity onto a related object's activity stream.

    `scope` is used as both the `log_activity(scope=...)` and `Change.type` value.
    `resolve_name` derives the display name for the activity row; the default
    just returns the precomputed `related_object_name`.
    """

    scope: str
    resolve_name: Callable[[TaggedItem, Optional[str]], Optional[str]] = lambda tagged_item, default_name: default_name


RELATED_OBJECT_ACTIVITY_LOGGERS: dict[str, RelatedObjectActivityLogger] = {
    "ticket": RelatedObjectActivityLogger(
        scope="Ticket",
        resolve_name=lambda tagged_item, default_name: (
            f"Ticket #{tagged_item.ticket.ticket_number}" if tagged_item.ticket else default_name
        ),
    ),
    "account": RelatedObjectActivityLogger(scope="Account"),
    "endpoint": RelatedObjectActivityLogger(scope="Endpoint"),
}


@mutable_receiver(model_activity_signal, sender=TaggedItem)
def handle_tagged_item_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    tagged_item = after_update or before_update

    if not tagged_item or not tagged_item.tag:
        return

    related_object_type, related_object_id, related_object_name = get_tagged_item_related_object_info(tagged_item)

    context = TaggedItemContext(
        tag_name=tagged_item.tag.name,
        tag_id=str(tagged_item.tag.id),
        team_id=tagged_item.tag.team_id,
        related_object_type=related_object_type,
        related_object_id=related_object_id,
        related_object_name=related_object_name,
    )

    team = tagged_item.tag.team
    organization_id = team.organization_id if team else None
    team_id = tagged_item.tag.team_id

    log_activity(
        organization_id=organization_id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=tagged_item.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=tagged_item.tag.name,
            context=context,
        ),
    )

    # Mirror the tag change onto the related object's own activity stream
    # (e.g. so a tag added to a Ticket shows up on that ticket's timeline).
    related_logger = RELATED_OBJECT_ACTIVITY_LOGGERS.get(related_object_type or "")
    if related_logger and related_object_id:
        tag_action: Literal["created", "deleted"] = "created" if activity == "created" else "deleted"
        log_activity(
            organization_id=organization_id,
            team_id=team_id,
            user=user,
            was_impersonated=was_impersonated,
            item_id=related_object_id,
            scope=related_logger.scope,
            activity="updated",
            detail=Detail(
                name=related_logger.resolve_name(tagged_item, related_object_name),
                changes=[
                    Change(
                        type=related_logger.scope,
                        field="tag",
                        action=tag_action,
                        after=tagged_item.tag.name if activity == "created" else None,
                        before=tagged_item.tag.name if activity == "deleted" else None,
                    )
                ],
            ),
        )


@mutable_receiver(model_activity_signal, sender=Organization)
def handle_organization_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    log_activity(
        organization_id=after_update.id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=after_update.name,
        ),
    )


@dataclasses.dataclass(frozen=True)
class OrganizationMembershipContext(ActivityContextBase):
    organization_id: str
    organization_name: str
    user_id: str
    user_email: str
    user_name: str
    level: str


@dataclasses.dataclass(frozen=True)
class OrganizationInviteContext(ActivityContextBase):
    organization_id: str
    organization_name: str
    target_email: str
    inviter_user_id: str | None
    inviter_user_email: str | None
    inviter_user_name: str | None
    level: str


@mutable_receiver(model_activity_signal, sender=OrganizationMembership)
def handle_organization_membership_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    membership = after_update or before_update

    if not membership:
        return

    member_user = membership.user
    member_name = f"{member_user.first_name} {member_user.last_name}".strip()

    context = OrganizationMembershipContext(
        organization_id=str(membership.organization_id),
        organization_name=membership.organization.name,
        user_id=str(member_user.id),
        user_email=member_user.email,
        user_name=member_name,
        level=str(OrganizationMembership.Level(membership.level).label),
    )

    if activity == "created":
        detail_name = f"{member_name} ({member_user.email}) joined {membership.organization.name}"
    elif activity == "deleted":
        detail_name = f"{member_name} ({member_user.email}) left {membership.organization.name}"
    else:
        detail_name = f"{member_name} ({member_user.email}) membership updated in {membership.organization.name}"

    log_activity(
        organization_id=membership.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=membership.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )


@mutable_receiver(model_activity_signal, sender=OrganizationInvite)
def handle_organization_invite_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    # Use after_update for create/update, before_update for delete
    invite = after_update or before_update

    if not invite:
        return

    inviter_user = invite.created_by
    inviter_name = f"{inviter_user.first_name} {inviter_user.last_name}".strip() if inviter_user else None

    context = OrganizationInviteContext(
        organization_id=str(invite.organization_id),
        organization_name=invite.organization.name,
        target_email=invite.target_email,
        inviter_user_id=str(inviter_user.id) if inviter_user else None,
        inviter_user_email=inviter_user.email if inviter_user else None,
        inviter_user_name=inviter_name,
        level=str(OrganizationMembership.Level(invite.level).label),
    )

    if activity == "created":
        if inviter_user:
            detail_name = f"User {inviter_name} ({inviter_user.email}) invited user {invite.target_email} into organization {invite.organization.name}"
        else:
            detail_name = f"User {invite.target_email} was invited to organization {invite.organization.name}"
    elif activity == "deleted":
        detail_name = f"Invite for {invite.target_email} to organization {invite.organization.name} was cancelled"
    else:
        detail_name = f"Invite for {invite.target_email} to organization {invite.organization.name} was updated"

    log_activity(
        organization_id=invite.organization_id,
        team_id=None,
        user=user,
        was_impersonated=was_impersonated,
        item_id=invite.id,
        scope=scope,
        activity=activity,
        detail=Detail(
            changes=changes_between(scope, previous=before_update, current=after_update),
            name=detail_name,
            context=context,
        ),
    )


@mutable_receiver(model_activity_signal, sender=PersonalAPIKey)
def handle_personal_api_key_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    changes = changes_between(scope, previous=before_update, current=after_update)

    # Check if scope changed (scoped_teams or scoped_organizations)
    scope_fields = ["scoped_teams", "scoped_organizations"]
    scope_changed = any(change.field in scope_fields for change in changes if change.field)

    if scope_changed and activity == "updated":
        # Filter out scope fields from changes as we dont want to present them to the user
        filtered_changes = [
            change for change in changes if change.field not in ["scoped_teams", "scoped_organizations"]
        ]
        log_personal_api_key_scope_change(before_update, after_update, user, was_impersonated, filtered_changes)
    else:
        log_personal_api_key_activity(after_update, activity, user, was_impersonated, changes)


@receiver(pre_delete, sender=PersonalAPIKey)
def handle_personal_api_key_delete(sender, instance, **kwargs):
    from posthog.models.activity_logging.model_activity import get_current_user, get_was_impersonated

    log_personal_api_key_activity(instance, "deleted", get_current_user(), get_was_impersonated())


@mutable_receiver(model_activity_signal, sender=ProjectSecretAPIKey)
def handle_project_secret_api_key_change(
    sender, scope, before_update, after_update, activity, user, was_impersonated=False, **kwargs
):
    changes = changes_between(scope, previous=before_update, current=after_update)
    log_project_secret_api_key_activity(after_update, activity, user, was_impersonated, changes)


@receiver(pre_delete, sender=ProjectSecretAPIKey)
def handle_project_secret_api_key_delete(sender, instance, **kwargs):
    log_project_secret_api_key_activity(instance, "deleted", get_current_user(), get_was_impersonated())


# --- Login session/device bookkeeping, relocated from posthog.api.authentication ---------
# user_logged_in fires wherever login happens; wiring this via the API module meant it only
# connected once the URLconf had been imported — an ordering that web happens to satisfy but
# nothing guarantees.

USER_AUTH_METHOD_MISMATCH = Counter(
    "user_auth_method_mismatches_sso_enforcement",
    "A user successfully authenticated with a different method than the one they're required to use",
    labelnames=["login_method", "sso_enforced_method", "user_uuid"],
)


@receiver(user_logged_in)
def post_login(sender, user, request: HttpRequest, **kwargs):
    """
    Runs after every user login (including tests)
    Sets SESSION_COOKIE_CREATED_AT_KEY in the session to the current time
    """

    if hasattr(request, "backend"):
        sso_enforcement = OrganizationDomain.objects.get_sso_enforcement_for_email_address(user.email)
        if sso_enforcement is not None and sso_enforcement != request.backend.name:
            USER_AUTH_METHOD_MISMATCH.labels(
                login_method=request.backend.name, sso_enforced_method=sso_enforcement, user_uuid=user.uuid
            ).inc()

    request.session[settings.SESSION_COOKIE_CREATED_AT_KEY] = time.time()

    # Every (re)auth refreshes the step-up window and drops any pending step-up requirement, so a
    # fresh password/2FA/SSO login satisfies TimeSensitiveActionPermission.
    request.session[settings.SESSION_LAST_REAUTH_AT_KEY] = time.time()
    request.session.pop(settings.SESSION_STEP_UP_REQUIRED_KEY, None)

    # Defensive risk-baseline reset: login() rotates the session key, so the new row's risk columns
    # are already NULL and this is normally a no-op. It guarantees a clean baseline after a high-tier
    # logout→re-login so the next request re-establishes from the real location instead of oscillating.
    # Only the security baseline is cleared (not last_activity, which is display-only).
    if request.session.session_key:
        Session.objects.filter(session_key=request.session.session_key).update(
            latitude=None, longitude=None, country_code=None, ua_signature=None, baseline_at=None
        )

    # Cache device info on signup to skip login notification for this device
    if user.last_login is None:
        short_user_agent = get_short_user_agent(request)
        ip_address = get_ip_address(request)
        country = get_geoip_properties(ip_address).get("$geoip_country_name", "Unknown")
        check_and_cache_login_device(user.id, country, short_user_agent)
