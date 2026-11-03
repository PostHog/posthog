import hashlib
import secrets
from typing import cast
from urllib.parse import quote, urlencode, urlparse
from uuid import UUID

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import connection, transaction
from django.http import HttpResponse, HttpResponseRedirect

import structlog
from cryptography.fernet import InvalidToken
from rest_framework import decorators, exceptions, permissions, serializers, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.exceptions_capture import capture_exception
from posthog.helpers.oauth_pending_connection import shared_cookie_domain
from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.organization_integration import OrganizationIntegration
from posthog.models.team import Team
from posthog.models.user import User

from ee.api.vercel.crypto import decrypt_payload, encrypt_payload, mark_token_used, release_used_token
from ee.vercel.client import APIError, OAuthTokenResponse, VercelAPIClient

logger = structlog.get_logger(__name__)


class VercelImportError(Exception):
    pass


ALLOWED_REDIRECT_DOMAINS = {
    "vercel.com",
    "www.vercel.com",
}

CONNECT_SESSION_TIMEOUT = 600  # 10 minutes
CONNECT_SALT = "vercel_connect"
CONNECT_NONCE_COOKIE_PREFIX = "ph_vercel_connect_"
CONNECT_NONCE_COOKIE_PATH = "/api/vercel/connect"
INSTALL_STATE_COOKIE_PREFIX = "__Host-ph_vercel_install_state_"
MAX_PENDING_INSTALL_STATES = 5
INSTALL_CONTINUATION_CACHE_PREFIX = "vercel_connect_install_next:"
INSTALL_CONTINUATION_SALT = "vercel_connect_install"
SESSION_INVALID_MESSAGE = "Session expired or invalid. Please try linking again from Vercel."
_BROWSER_NONCE_KEY = "browser_nonce"


def _sign_connect_session(data: dict, browser_nonce: str) -> str:
    return encrypt_payload({**data, _BROWSER_NONCE_KEY: browser_nonce}, salt=CONNECT_SALT, jti=True)


def _load_connect_session(token: str) -> dict:
    try:
        return decrypt_payload(token, salt=CONNECT_SALT, ttl=CONNECT_SESSION_TIMEOUT)
    except InvalidToken:
        raise signing.BadSignature("Invalid or expired token")


def _per_flow_cookie_name(prefix: str, flow_secret: str) -> str:
    # One cookie per link flow, so a second flow in the same browser does not replace the first flow's cookie.
    return prefix + hashlib.sha256(flow_secret.encode()).hexdigest()[:16]


def _browser_nonce_cookie_name(browser_nonce: str) -> str:
    return _per_flow_cookie_name(CONNECT_NONCE_COOKIE_PREFIX, browser_nonce)


def _set_browser_nonce_cookie(request: Request, response: HttpResponse, browser_nonce: str) -> None:
    response.set_cookie(
        _browser_nonce_cookie_name(browser_nonce),
        browser_nonce,
        max_age=CONNECT_SESSION_TIMEOUT,
        path=CONNECT_NONCE_COOKIE_PATH,
        # The link page can run on the other cloud region, so the cookie must reach both regions.
        domain=shared_cookie_domain(request),
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=True,
        samesite="Lax",
    )


def _clear_browser_nonce_cookie(request: Request, response: HttpResponse, browser_nonce: str) -> None:
    response.delete_cookie(
        _browser_nonce_cookie_name(browser_nonce),
        path=CONNECT_NONCE_COOKIE_PATH,
        domain=shared_cookie_domain(request),
        samesite="Lax",
    )


def _load_browser_bound_session(request: Request, token: str) -> dict:
    try:
        session = _load_connect_session(token)
    except signing.BadSignature:
        raise exceptions.ValidationError(SESSION_INVALID_MESSAGE)

    session_nonce = session.get(_BROWSER_NONCE_KEY)
    if not isinstance(session_nonce, str):
        reason = "token_without_nonce"
    else:
        cookie_nonce = request.COOKIES.get(_browser_nonce_cookie_name(session_nonce), "")
        if not cookie_nonce:
            reason = "missing_cookie"
        elif secrets.compare_digest(cookie_nonce.encode(), session_nonce.encode()):
            return session
        else:
            reason = "nonce_mismatch"

    capture_exception(
        Exception("Vercel connect: session used by a browser that did not start it"),
        {"reason": reason, "integration": "vercel"},
    )
    raise exceptions.ValidationError(SESSION_INVALID_MESSAGE)


def _install_state_cookie_name(state: str) -> str:
    return _per_flow_cookie_name(INSTALL_STATE_COOKIE_PREFIX, state)


def _install_continuation_cache_key(state: str) -> str:
    return INSTALL_CONTINUATION_CACHE_PREFIX + hashlib.sha256(state.encode()).hexdigest()


def _save_install_continuation(state: str, continuation: dict) -> None:
    cache.set(
        _install_continuation_cache_key(state),
        encrypt_payload(continuation, salt=INSTALL_CONTINUATION_SALT, jti=False),
        timeout=CONNECT_SESSION_TIMEOUT,
    )


def _install_continuation(state: str) -> dict | None:
    token = cache.get(_install_continuation_cache_key(state))
    if not token:
        return None
    try:
        return decrypt_payload(token, salt=INSTALL_CONTINUATION_SALT, ttl=CONNECT_SESSION_TIMEOUT)
    except InvalidToken:
        return None


def _forget_install_continuation(state: str) -> None:
    # Runs after Vercel's code is spent, so failing here would strand the user; the entry expires anyway.
    try:
        cache.delete(_install_continuation_cache_key(state))
    except Exception as e:
        capture_exception(e, {"reason": "install_continuation_cleanup_failed", "integration": "vercel"})


def _drop_excess_install_state_cookies(request: Request, response: HttpResponse) -> None:
    # Any code starts a flow before it is validated, and every request to this host carries these cookies.
    pending = sorted(name for name in request.COOKIES if name.startswith(INSTALL_STATE_COOKIE_PREFIX))
    for name in pending[MAX_PENDING_INSTALL_STATES - 1 :]:
        response.delete_cookie(name, path="/", samesite="Lax")


def _redirect_through_vercel_install(request: Request, continuation: dict) -> HttpResponse:
    # A Marketplace install calls back without a state, so nothing ties its code to this browser. Vercel's
    # external install flow returns the state we send, and the state cookie ties that state to this browser.
    state = secrets.token_urlsafe(32)
    slug = quote(settings.VERCEL_INTEGRATION_SLUG, safe="")
    response = HttpResponseRedirect(f"https://vercel.com/integrations/{slug}/new?{urlencode({'state': state})}")
    _save_install_continuation(state, continuation)
    _drop_excess_install_state_cookies(request, response)
    response.set_cookie(
        _install_state_cookie_name(state),
        state,
        max_age=CONNECT_SESSION_TIMEOUT,
        # The __Host- prefix stops a sibling posthog.com subdomain from setting a state cookie that passes the check.
        # A host-only cookie is enough because Vercel sends both callback requests to the one configured Redirect URL.
        path="/",
        secure=True,
        httponly=True,
        samesite="Lax",
    )
    return response


def _clear_install_state_cookie(response: HttpResponse, state: str) -> None:
    response.delete_cookie(_install_state_cookie_name(state), path="/", samesite="Lax")


def _reject_install_return_without_state(request: Request) -> None:
    if request.query_params.get("source") != "external":
        return

    # Vercel's install page sent this request without the state we gave it, so another redirect could loop.
    capture_exception(
        Exception("Vercel connect: install returned without a state"),
        {"reason": "missing_state_after_install_redirect", "integration": "vercel"},
    )
    raise exceptions.ValidationError(SESSION_INVALID_MESSAGE)


def _require_install_state_from_this_browser(request: Request, state: str) -> None:
    cookie_state = request.COOKIES.get(_install_state_cookie_name(state), "")
    if not cookie_state:
        reason = "missing_state_cookie"
    elif secrets.compare_digest(cookie_state.encode(), state.encode()):
        return
    else:
        reason = "state_mismatch"

    capture_exception(
        Exception("Vercel connect: install state used by a browser that did not start it"),
        {"reason": reason, "integration": "vercel"},
    )
    raise exceptions.ValidationError(SESSION_INVALID_MESSAGE)


def _require_same_vercel_user(continuation: dict, install_grant: OAuthTokenResponse) -> None:
    if secrets.compare_digest(continuation["user_id"].encode(), install_grant.user_id.encode()):
        return

    capture_exception(
        Exception("Vercel connect: install page returned a different Vercel user"),
        {"reason": "install_user_mismatch", "integration": "vercel"},
    )
    raise exceptions.ValidationError(SESSION_INVALID_MESSAGE)


def _exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> OAuthTokenResponse:
    token_response = VercelAPIClient(bearer_token=None).oauth_token_exchange(
        code=code,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
    )
    if token_response.error:
        logger.error(
            "vercel_connect_token_exchange_failed",
            error=token_response.error,
            error_description=token_response.error_description,
            integration="vercel",
        )
        raise exceptions.AuthenticationFailed("Vercel authentication failed")
    return token_response


def _mark_token_used(jti: str) -> bool:
    return mark_token_used(jti, ttl=CONNECT_SESSION_TIMEOUT)


def _validate_next_url(url: str) -> str:
    """Validate and sanitize the next_url to prevent open redirects."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.scheme not in ("https", "http"):
        return ""
    if not parsed.hostname or parsed.hostname not in ALLOWED_REDIRECT_DOMAINS:
        return ""
    return url


def _is_installation_orphaned(integration: OrganizationIntegration) -> bool:
    """Return True if Vercel no longer recognises this installation (401/403/404).

    Returns False when Vercel confirms the installation is active, or when
    we cannot reach Vercel (network/5xx) -- in that ambiguous case we keep
    the existing integration to avoid accidental deletion.
    """
    access_token = integration.sensitive_config.get("credentials", {}).get("access_token")
    if not access_token:
        return False

    installation_id = integration.integration_id
    if not installation_id:
        return False

    client = VercelAPIClient(bearer_token=access_token)
    try:
        return not client.check_installation_active(installation_id)
    except APIError:
        return False


def _lock_vercel_links(organization_id: UUID) -> None:
    # Serializes orphan cleanup with link creation for one organization. The lock is transaction-scoped,
    # so call it inside `transaction.atomic()` and never around the Vercel network call.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"vercel-connect:{organization_id}"])


def _mapped_team_ids(integration: OrganizationIntegration) -> set[int] | None:
    mapping = integration.config.get("environment_mapping")
    if not mapping:
        return None
    return {team_id for team_id in mapping.values() if isinstance(team_id, int)}


def _delete_orphaned_integration(integration: OrganizationIntegration) -> None:
    with transaction.atomic():
        _lock_vercel_links(integration.organization_id)
        if not OrganizationIntegration.objects.filter(pk=integration.pk).exists():
            return

        # A resource records its team, not its installation, so a resource is safe to delete only when no
        # other installation claims its team. A resource left behind blocks the next link attempt, because
        # `complete` rejects a team that still has one.
        claimed_team_ids: set[int] = set()
        for sibling in OrganizationIntegration.objects.filter(
            organization_id=integration.organization_id,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).exclude(pk=integration.pk):
            sibling_team_ids = _mapped_team_ids(sibling)
            if sibling_team_ids is None:
                # A sibling without a mapping may own any team, so no resource is safe to delete.
                integration.delete()
                return
            claimed_team_ids |= sibling_team_ids

        Integration.objects.filter(
            team__organization_id=integration.organization_id,
            kind=Integration.IntegrationKind.VERCEL,
        ).exclude(team_id__in=claimed_team_ids).delete()
        integration.delete()


class VercelConnectCallbackViewSet(viewsets.GenericViewSet):
    """Handles the Vercel connectable account (Link Existing Account) flow.

    When a user clicks "Link Existing Account" in the Vercel Marketplace,
    Vercel opens a popup to our Redirect URL with an OAuth code.
    We exchange the code for an access token and then link the user's
    existing PostHog org to the Vercel installation.
    """

    permission_classes = [permissions.AllowAny]

    @decorators.action(detail=False, methods=["get"], url_path="callback")
    def callback(self, request: Request) -> HttpResponse:
        code = request.query_params.get("code")
        next_url = _validate_next_url(request.query_params.get("next", ""))
        configuration_id = request.query_params.get("configurationId", "")

        if not code:
            raise exceptions.ValidationError("Missing code parameter")

        client_id = getattr(settings, "VERCEL_CLIENT_INTEGRATION_ID", "")
        client_secret = getattr(settings, "VERCEL_CLIENT_INTEGRATION_SECRET", "")
        redirect_uri = f"{settings.SITE_URL}/connect/vercel/callback"

        if not client_id or not client_secret:
            logger.error("vercel_connect_missing_configuration", integration="vercel")
            capture_exception(Exception("Vercel connect: missing client configuration"))
            raise exceptions.APIException("Vercel integration not configured")

        state = request.query_params.get("state")
        if not state:
            _reject_install_return_without_state(request)
            # Vercel waits for the import on the installation of this Marketplace code, so keep its grant.
            # The install page code only proves which Vercel user holds this browser.
            marketplace_grant = _exchange_code(code, client_id, client_secret, redirect_uri)
            return _redirect_through_vercel_install(
                request,
                {
                    "access_token": marketplace_grant.access_token,
                    "token_type": marketplace_grant.token_type,
                    "installation_id": marketplace_grant.installation_id,
                    "user_id": marketplace_grant.user_id,
                    "team_id": marketplace_grant.team_id,
                    "configuration_id": configuration_id,
                    "next_url": next_url,
                },
            )
        _require_install_state_from_this_browser(request, state)
        continuation = _install_continuation(state)
        if continuation is None:
            capture_exception(
                Exception("Vercel connect: install state has no Marketplace grant"),
                {"reason": "missing_marketplace_grant", "integration": "vercel"},
            )
            raise exceptions.ValidationError(SESSION_INVALID_MESSAGE)

        _require_same_vercel_user(continuation, _exchange_code(code, client_id, client_secret, redirect_uri))

        browser_nonce = secrets.token_urlsafe(32)
        session_token = _sign_connect_session(
            {**continuation, "next_url": continuation.get("next_url") or next_url},
            browser_nonce=browser_nonce,
        )

        link_url = f"/connect/vercel/link?{urlencode({'session': session_token})}"

        if not request.user.is_authenticated:
            login_url = f"/login?next={quote(link_url)}"
            response = HttpResponseRedirect(redirect_to=login_url)
        else:
            response = HttpResponseRedirect(redirect_to=link_url)

        _set_browser_nonce_cookie(request, response, browser_nonce)
        _clear_install_state_cookie(response, state)
        _forget_install_continuation(state)
        return response


class EnvironmentMappingSerializer(serializers.Serializer):
    production = serializers.IntegerField(required=True)
    preview = serializers.IntegerField(required=False)
    development = serializers.IntegerField(required=False)


class VercelConnectLinkSerializer(serializers.Serializer):
    session = serializers.CharField(required=True)
    organization_id = serializers.UUIDField(required=True)
    environment_mapping = EnvironmentMappingSerializer(required=True)


class VercelConnectLinkViewSet(viewsets.GenericViewSet):
    """API endpoint to complete the Vercel connectable account linking."""

    permission_classes = [permissions.IsAuthenticated]

    @decorators.action(detail=False, methods=["post"], url_path="complete")
    def complete(self, request: Request) -> Response:
        serializer = VercelConnectLinkSerializer(data=request.data)
        if not serializer.is_valid():
            raise exceptions.ValidationError(serializer.errors)

        user = cast(User, request.user)
        session_key = serializer.validated_data["session"]
        organization_id = serializer.validated_data["organization_id"]
        env_mapping = serializer.validated_data["environment_mapping"]
        production_team_id = env_mapping["production"]
        preview_team_id = env_mapping.get("preview", production_team_id)
        development_team_id = env_mapping.get("development", production_team_id)

        cached_data = _load_browser_bound_session(request, session_key)

        jti = cached_data.get("jti")
        if not jti or not _mark_token_used(jti):
            raise exceptions.ValidationError("Session already used. Please try linking again from Vercel.")

        try:
            membership = OrganizationMembership.objects.get(
                user=user,
                organization_id=organization_id,
            )
        except OrganizationMembership.DoesNotExist:
            raise exceptions.PermissionDenied("You are not a member of this organization.")

        if membership.level < OrganizationMembership.Level.ADMIN:
            raise exceptions.PermissionDenied("You must be an admin or owner to link this organization.")

        organization = membership.organization
        installation_id = cached_data["installation_id"]

        existing = OrganizationIntegration.objects.filter(
            organization=organization,
            kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
        ).first()

        if existing:
            if _is_installation_orphaned(existing):
                logger.info(
                    "vercel_connect_deleting_orphaned_integration",
                    old_installation_id=existing.integration_id,
                    organization_id=str(organization_id),
                    integration="vercel",
                )
                _delete_orphaned_integration(existing)
            else:
                raise exceptions.ValidationError(
                    "This organization already has a Vercel integration. "
                    "Please unlink the existing one first or choose a different organization."
                )

        unique_team_ids = {production_team_id, preview_team_id, development_team_id}
        teams_by_id: dict[int, Team] = {}
        for tid in unique_team_ids:
            try:
                teams_by_id[tid] = Team.objects.get(pk=tid, organization=organization)
            except Team.DoesNotExist:
                raise exceptions.ValidationError(f"Project {tid} does not belong to this organization.")

        for tid in unique_team_ids:
            if IntegrationManager.vercel.oauth.exists(tid):
                raise exceptions.ValidationError(f"Project '{teams_by_id[tid].name}' already has a Vercel integration.")

        production_team = teams_by_id[production_team_id]

        with transaction.atomic():
            _lock_vercel_links(organization.id)
            org_integration = OrganizationIntegration.objects.create(
                organization=organization,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
                integration_id=installation_id,
                config={
                    "type": "connectable",
                    "vercel_team_id": cached_data.get("team_id"),
                    "vercel_user_id": cached_data["user_id"],
                    "configuration_id": cached_data.get("configuration_id"),
                    "environment_mapping": {
                        "production": production_team_id,
                        "preview": preview_team_id,
                        "development": development_team_id,
                    },
                    "user_mappings": {
                        cached_data["user_id"]: user.pk,
                    },
                },
                sensitive_config={
                    "credentials": {
                        "access_token": cached_data["access_token"],
                        "token_type": cached_data["token_type"],
                    },
                },
                created_by=user,
            )

            resources: dict[int, IntegrationRecord] = {}
            for tid, team in teams_by_id.items():
                resources[tid] = IntegrationManager.vercel.oauth.create(
                    team.pk,
                    external_id=str(team.pk),
                    config={"type": "connectable"},
                    created_by_id=user.pk,
                )

        from ee.vercel.integration import VercelIntegration

        production_resource = resources[production_team_id]
        env_secrets = self._build_env_secrets(teams_by_id, production_team_id, preview_team_id, development_team_id)

        client = VercelAPIClient(bearer_token=cached_data["access_token"])
        import_result = client.import_resource(
            integration_config_id=installation_id,
            resource_id=str(production_resource.id),
            product_id="posthog",
            name=production_team.name,
            secrets=env_secrets,
        )
        if not import_result.success:
            resource_id = str(production_resource.id)
            logger.error(
                "Failed to import resource to Vercel",
                error=import_result.error,
                status_code=import_result.status_code,
                error_detail=import_result.error_detail,
                installation_id=installation_id,
                resource_id=resource_id,
                integration="vercel",
            )

            with transaction.atomic():
                org_integration.delete()
                for resource in resources.values():
                    IntegrationManager.vercel.oauth.delete(resource.team_id, resource.id, ignore_usages=True)

            # The rollback leaves nothing behind, so the same session can try the link again.
            release_used_token(jti)

            capture_exception(
                VercelImportError("Vercel did not accept the resource import"),
                {
                    "status_code": import_result.status_code,
                    "error": import_result.error,
                    "error_detail": import_result.error_detail,
                    "installation_id": installation_id,
                    "resource_id": resource_id,
                    "organization_id": str(organization.id),
                },
            )
            if import_result.status_code is not None:
                raise exceptions.ValidationError(
                    f"Vercel rejected the link (HTTP {import_result.status_code}). Start the link again from Vercel."
                )
            raise exceptions.ValidationError(
                f"Vercel did not accept the link ({import_result.error}). Start the link again from Vercel."
            )

        VercelIntegration.bulk_sync_feature_flags_to_vercel(production_team)

        logger.info(
            "Vercel connectable account linked",
            installation_id=installation_id,
            organization_id=str(organization_id),
            production_team_id=production_team_id,
            user_id=user.pk,
            integration="vercel",
        )

        response = Response(
            {
                "status": "linked",
                "organization_id": str(organization_id),
                "organization_name": organization.name,
                "next_url": cached_data.get("next_url", ""),
            },
            status=201,
        )
        _clear_browser_nonce_cookie(request, response, cached_data[_BROWSER_NONCE_KEY])
        return response

    @staticmethod
    def _build_env_secrets(
        teams_by_id: dict[int, Team],
        production_id: int,
        preview_id: int,
        development_id: int,
    ) -> list[dict]:
        from posthog.utils import absolute_uri

        from ee.vercel.integration import CLIENT_ENV_PREFIXES

        prod_team = teams_by_id[production_id]
        preview_team = teams_by_id[preview_id]
        dev_team = teams_by_id[development_id]

        all_same = production_id == preview_id == development_id
        host = absolute_uri()

        env_secrets: list[dict] = []
        for prefix in CLIENT_ENV_PREFIXES:
            env_secrets.append(
                {
                    "name": f"{prefix}POSTHOG_PROJECT_TOKEN",
                    "value": prod_team.api_token,
                    **(
                        {}
                        if all_same
                        else {
                            "environmentOverrides": {
                                "preview": preview_team.api_token,
                                "development": dev_team.api_token,
                            }
                        }
                    ),
                }
            )
            env_secrets.append({"name": f"{prefix}POSTHOG_HOST", "value": host})
        return env_secrets

    @decorators.action(detail=False, methods=["get"], url_path="session")
    def session_info(self, request: Request) -> Response:
        session_key = request.query_params.get("session")
        if not session_key:
            raise exceptions.ValidationError("Missing session parameter")

        cached_data = _load_browser_bound_session(request, session_key)

        user = cast(User, request.user)
        memberships = OrganizationMembership.objects.filter(
            user=user,
            level__gte=OrganizationMembership.Level.ADMIN,
        ).select_related("organization")

        org_ids = [m.organization_id for m in memberships]
        vercel_integrations = {
            i.organization_id: i
            for i in OrganizationIntegration.objects.filter(
                organization_id__in=org_ids,
                kind=OrganizationIntegration.OrganizationIntegrationKind.VERCEL,
            )
        }

        orphaned_org_ids: set = set()
        for org_id, integration in vercel_integrations.items():
            if _is_installation_orphaned(integration):
                logger.info(
                    "vercel_session_deleting_orphaned_integration",
                    installation_id=integration.integration_id,
                    organization_id=str(org_id),
                    integration="vercel",
                )
                _delete_orphaned_integration(integration)
                orphaned_org_ids.add(org_id)

        teams_by_org: dict = {}
        for team in Team.objects.filter(organization_id__in=org_ids).order_by("name"):
            teams_by_org.setdefault(team.organization_id, []).append(team)

        teams_with_vercel = set(
            Integration.objects.filter(
                team__organization_id__in=org_ids,
                kind=Integration.IntegrationKind.VERCEL,
            ).values_list("team_id", flat=True)
        )

        organizations = [
            {
                "id": str(m.organization.id),
                "name": m.organization.name,
                "already_linked": m.organization_id in vercel_integrations
                and m.organization_id not in orphaned_org_ids,
                "teams": [
                    {
                        "id": t.pk,
                        "name": t.name,
                        "already_linked": t.pk in teams_with_vercel,
                    }
                    for t in teams_by_org.get(m.organization_id, [])
                ],
            }
            for m in memberships
        ]

        return Response(
            {
                "next_url": cached_data.get("next_url", ""),
                "organizations": organizations,
            }
        )
