"""POST /provisioning/client_registration — register a partner client and report why it
does or does not work.

This is the one door into the namespace: every other endpoint requires an already-registered
client and points here when it doesn't find one. Registration is synchronous so a partner
knows the outcome from the response rather than polling, and each check is reported
individually so a broken setup names its own cause instead of surfacing as a bare 401.

Deliberately unauthenticated: a partner that has not registered yet has no credential to
present, so requiring one would make the endpoint useless for the case it exists to serve.
What that exposes is bounded — the only URL a caller can make us dereference is the one it is
claiming as its own client_id, which goes through the same SSRF validation, DNS check and
blocklist as any other CIMD fetch — and it is rate limited per client_id, per IP and per
domain because the fetch is synchronous.
"""

from __future__ import annotations

from typing import Any

from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.oauth.cimd import (
    CIMDFetchError,
    CIMDValidationError,
    apply_provisioning_defaults,
    fetch_and_upsert_cimd_application,
    get_application_by_client_id,
    is_cimd_client_id,
    is_cimd_url_blocked,
)
from posthog.api.oauth.client_assertion import ClientAssertionError, describe_jwks, verify_client_assertion
from posthog.models.oauth import OAuthApplication

from ee.api.agentic_provisioning.analytics import capture_provisioning_event
from ee.api.agentic_provisioning.exceptions import ProvisioningError
from ee.api.agentic_provisioning.serializers import ClientRegistrationSerializer
from ee.api.agentic_provisioning.throttling import CIMDRegistrationThrottle, ClientRegistrationThrottle
from ee.api.agentic_provisioning.views.base import ProvisioningAPIView


class ClientRegistrationView(ProvisioningAPIView):
    # Unauthenticated by design, see the module docstring.
    authenticates_in_handler = True
    partner_throttle_classes = [ClientRegistrationThrottle, CIMDRegistrationThrottle]

    def post(self, request: Request) -> Response:
        data = self.validated_body(ClientRegistrationSerializer, request)
        client_id = data["client_id"]
        checks: list[dict[str, Any]] = []

        app = self._register_or_resolve(client_id, checks)
        if app is None:
            # Nothing else can be said about a client we could not resolve, and the caller
            # needs a failure status rather than a 200 that looks like success.
            raise ProvisioningError(
                "registration_failed",
                _first_failure(checks) or "Could not register this client",
                extra={"client_id": client_id, "registered": False, "checks": checks},
            )

        self._check_jwks(app, checks)
        if data["client_assertion"]:
            self._check_assertion(app, data["client_assertion"], checks)

        capture_provisioning_event(
            "client_registration",
            "checked",
            partner=app,
            passed=all(check["ok"] for check in checks),
        )
        return Response(
            {
                "client_id": app.effective_client_id,
                "registered": True,
                "client_type": app.client_type,
                "token_endpoint_auth_method": app.token_endpoint_auth_method.value,
                "jwks_uri": app.jwks_uri,
                "scopes": app.ceiling_scopes,
                "provisioning": {
                    "active": app.provisioning.active,
                    "can_create_accounts": app.provisioning.can_create_accounts,
                    "can_provision_resources": app.provisioning.can_provision_resources,
                },
                # Spelled out because "why can't I call github/grants" is the question this
                # endpoint exists to answer, and the rule (a confidential client PostHog granted
                # the capability to) is not something a partner can infer from its own metadata
                # document.
                "capabilities": {
                    "account_requests": app.provisioning.active and app.provisioning.can_create_accounts,
                    "github_grants": (
                        app.requires_client_authentication
                        and app.provisioning.can_use_github_grants
                        and app.provisioning.can_create_accounts
                    ),
                    "wizard_runs": app.provisioning.active and app.provisioning.can_start_wizard_runs,
                },
                "checks": checks,
            }
        )

    def _register_or_resolve(self, client_id: str, checks: list[dict[str, Any]]) -> OAuthApplication | None:
        """Register a CIMD client from its metadata document, or look up a manually
        registered one. Returns None with the reason recorded in ``checks``."""
        if not is_cimd_client_id(client_id):
            # A non-CIMD client_id has no document to fetch, so it can only have been
            # registered by a PostHog admin.
            try:
                admin_registered = get_application_by_client_id(client_id)
            except OAuthApplication.DoesNotExist:
                _record(checks, "client_exists", False, "No client is registered with this client_id")
                return None
            _record(checks, "client_exists", True, "Registered by a PostHog admin")
            return self._require_partner(admin_registered, checks)

        if is_cimd_url_blocked(client_id):
            _record(checks, "metadata_document", False, "This client_id has been blocked")
            return None

        # An already-registered client keeps working when its document is momentarily
        # unreachable, so a failed re-fetch is reported as one failed check rather than
        # suppressing every other diagnostic the caller came for.
        existing = OAuthApplication.objects.filter(cimd_metadata_url=client_id).first()
        app: OAuthApplication | None
        try:
            app = fetch_and_upsert_cimd_application(client_id)
            if app is None:
                raise CIMDFetchError("Registration is already in progress, retry shortly")
        except (CIMDFetchError, CIMDValidationError) as exc:
            _record(checks, "metadata_document", False, str(exc))
            if existing is None:
                return None
            app = existing
        else:
            _record(checks, "metadata_document", True, "Fetched and validated")

        # A CIMD client that has never been used for provisioning carries no provisioning
        # config yet, so registering here is what makes the rest of the namespace reachable.
        if not app.is_provisioning_partner:
            apply_provisioning_defaults(app)
            app.refresh_from_db()
        return self._require_partner(app, checks)

    def _require_partner(self, app: OAuthApplication, checks: list[dict[str, Any]]) -> OAuthApplication | None:
        if not app.is_provisioning_partner:
            _record(checks, "provisioning_enabled", False, "This client is not enabled for agentic provisioning")
            return None
        if not app.provisioning.active:
            _record(checks, "provisioning_enabled", False, "Provisioning is deactivated for this client")
            return None
        _record(checks, "provisioning_enabled", True, "Active")
        return app

    def _check_jwks(self, app: OAuthApplication, checks: list[dict[str, Any]]) -> None:
        if not app.jwks_uri:
            # Not a failure: a public client legitimately publishes no keys. Reported so the
            # response says which of the two situations the caller is in.
            _record(
                checks,
                "jwks",
                True,
                "No jwks_uri, so this client authenticates with PKCE only and cannot use the GitHub grant endpoints",
            )
            return

        try:
            key_ids = describe_jwks(app.jwks_uri)
        except ClientAssertionError as exc:
            _record(checks, "jwks", False, str(exc))
            return
        _record(checks, "jwks", True, f"{len(key_ids)} key(s) served: {', '.join(key_ids)}")

    def _check_assertion(self, app: OAuthApplication, assertion: str, checks: list[dict[str, Any]]) -> None:
        try:
            verify_client_assertion(app, assertion)
        except ClientAssertionError as exc:
            _record(checks, "client_assertion", False, str(exc))
            return
        _record(checks, "client_assertion", True, "Verified, and its jti is now consumed")


def _record(checks: list[dict[str, Any]], name: str, ok: bool, detail: str) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})


def _first_failure(checks: list[dict[str, Any]]) -> str:
    return next((check["detail"] for check in checks if not check["ok"]), "")
