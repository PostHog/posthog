"""DB-touching helpers for the `phprov` CLI.

The CLI in `bin/phprov` is a pure HTTP client. Anything that requires a
Django app context (creating a partner OAuthApplication, decoding a stored
access token, dropping deep-link cache entries) lives here and is invoked
via `python manage.py phprov_partner <subcommand>`.

Subcommands:
  create        Create or update an OAuthApplication wired up as a
                provisioning partner.
  show          Print the partner config as JSON.
  delete        Delete a partner OAuthApplication by client_id.
  decode-token  Look up an OAuthAccessToken by its raw bearer value and
                print scope, scoped_teams, expiry, and owning app.
  evict-deep-link  Delete a deep-link cache entry by its token (useful for
                   replaying the redemption path in tests).
"""

from __future__ import annotations

import sys
import json
from typing import Any

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError, CommandParser

from posthog.models.oauth import OAuthAccessToken, OAuthApplication, find_oauth_access_token


class Command(BaseCommand):
    help = "DB helpers for the phprov CLI."

    def add_arguments(self, parser: CommandParser) -> None:
        sub = parser.add_subparsers(dest="subcommand", required=True)

        create = sub.add_parser("create", help="Create or update a provisioning partner OAuth app.")
        create.add_argument("--client-id", required=True)
        create.add_argument("--name", default="phprov test partner")
        create.add_argument(
            "--auth-method",
            choices=["pkce", "bearer", "hmac"],
            default="pkce",
            help="Provisioning auth method. pkce is the easiest for CLI testing.",
        )
        create.add_argument("--redirect-uri", default="http://localhost:9999/callback")
        create.add_argument(
            "--client-secret",
            default="",
            help="Empty for confidential public-style PKCE clients.",
        )
        create.add_argument(
            "--can-create-accounts",
            action="store_true",
            help="Set provisioning_can_create_accounts=True.",
        )
        create.add_argument(
            "--skip-existing-user-consent",
            action="store_true",
            help="Set provisioning_skip_existing_user_consent=True (only for trusted partners).",
        )

        show = sub.add_parser("show", help="Print partner config as JSON.")
        show.add_argument("--client-id", required=True)

        delete = sub.add_parser("delete", help="Delete a partner by client_id.")
        delete.add_argument("--client-id", required=True)

        decode = sub.add_parser("decode-token", help="Look up an access token by its bearer value.")
        decode.add_argument("--token", required=True)

        evict = sub.add_parser("evict-deep-link", help="Delete a deep-link cache entry.")
        evict.add_argument("--token", required=True)

    def handle(self, *args: Any, **options: Any) -> None:
        sub = options["subcommand"]
        if sub == "create":
            self._create(options)
        elif sub == "show":
            self._show(options["client_id"])
        elif sub == "delete":
            self._delete(options["client_id"])
        elif sub == "decode-token":
            self._decode_token(options["token"])
        elif sub == "evict-deep-link":
            self._evict_deep_link(options["token"])
        else:
            raise CommandError(f"Unknown subcommand: {sub}")

    def _create(self, opts: dict[str, Any]) -> None:
        defaults = {
            "name": opts["name"],
            "client_secret": opts["client_secret"],
            "client_type": OAuthApplication.CLIENT_CONFIDENTIAL,
            "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
            "redirect_uris": opts["redirect_uri"],
            "algorithm": "RS256",
            "provisioning_auth_method": opts["auth_method"],
            "provisioning_active": True,
            "provisioning_can_create_accounts": opts["can_create_accounts"],
            "provisioning_can_provision_resources": True,
            "provisioning_partner_type": "phprov",
            "provisioning_skip_existing_user_consent": opts["skip_existing_user_consent"],
        }
        app, created = OAuthApplication.objects.update_or_create(
            client_id=opts["client_id"],
            defaults=defaults,
        )
        self._emit(
            {
                "created": created,
                "id": str(app.id),
                "client_id": app.client_id,
                "auth_method": app.provisioning_auth_method,
                "active": app.provisioning_active,
                "can_create_accounts": app.provisioning_can_create_accounts,
                "can_provision_resources": app.provisioning_can_provision_resources,
            }
        )

    def _show(self, client_id: str) -> None:
        try:
            app = OAuthApplication.objects.get(client_id=client_id)
        except OAuthApplication.DoesNotExist:
            raise CommandError(f"No OAuthApplication with client_id={client_id}")
        self._emit(
            {
                "id": str(app.id),
                "client_id": app.client_id,
                "name": app.name,
                "auth_method": app.provisioning_auth_method,
                "active": app.provisioning_active,
                "partner_type": app.provisioning_partner_type,
                "can_create_accounts": app.provisioning_can_create_accounts,
                "can_provision_resources": app.provisioning_can_provision_resources,
                "skip_existing_user_consent": app.provisioning_skip_existing_user_consent,
                "redirect_uris": app.redirect_uris,
                "is_cimd_client": app.is_cimd_client,
                "cimd_metadata_url": app.cimd_metadata_url,
            }
        )

    def _delete(self, client_id: str) -> None:
        deleted, _ = OAuthApplication.objects.filter(client_id=client_id).delete()
        self._emit({"deleted": deleted, "client_id": client_id})

    def _decode_token(self, token: str) -> None:
        access_token = find_oauth_access_token(token)
        if access_token is None:
            raise CommandError("Token not found")
        assert isinstance(access_token, OAuthAccessToken)
        app = access_token.application
        self._emit(
            {
                "user_id": access_token.user_id,
                "scope": access_token.scope,
                "scoped_teams": access_token.scoped_teams,
                "expires": access_token.expires.isoformat() if access_token.expires else None,
                "application": {
                    "id": str(app.id) if app else None,
                    "client_id": app.client_id if app else None,
                    "name": app.name if app else None,
                    "auth_method": app.provisioning_auth_method if app else None,
                    "is_cimd_client": app.is_cimd_client if app else None,
                },
            }
        )

    def _evict_deep_link(self, token: str) -> None:
        from ee.api.agentic_provisioning.views import DEEP_LINK_CACHE_PREFIX

        existed = cache.delete(f"{DEEP_LINK_CACHE_PREFIX}{token}")
        self._emit({"deleted": bool(existed), "token": token})

    def _emit(self, payload: dict[str, Any]) -> None:
        json.dump(payload, sys.stdout, default=str)
        sys.stdout.write("\n")
