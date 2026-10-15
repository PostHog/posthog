import json
import hashlib
from datetime import datetime, timedelta
from functools import partial
from typing import Final, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction
from django.utils import timezone

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.models import Team, User
from posthog.models.utils import uuid7
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.cdp.backend.mcp_event_delivery import MCP_EVENT_NAME, verify_callback
from products.cdp.backend.mcp_event_destination import MCPEventDestination
from products.cdp.backend.mcp_event_filters import MCPEventFilterAccessValidator
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription
from products.cdp.backend.tasks.mcp_events import expire_mcp_event_subscriptions
from products.cdp.backend.validation import HogFunctionFiltersSerializer

EXPIRY_BATCH_SIZE: Final = 500
MAX_SUBSCRIPTIONS_PER_USER: Final = 20
MAX_SUBSCRIPTIONS_PER_PROJECT: Final = 100
MAX_TTL_MS: Final = 24 * 60 * 60 * 1000
SECRET_ROTATION_GRACE: Final = timedelta(minutes=5)
_DERIVED_FILTER_KEYS: Final = frozenset(
    {"bytecode", "bytecode_error", "bytecode_contract", "transpiled", "mcp_property_dependencies"}
)


class MCPEventSubscriptions:
    def __init__(self, *, team: Team, user: User, principal: str) -> None:
        self.team = team
        self.user = user
        self.principal = principal

    def normalize_filters(self, raw_filters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if raw_filters.get("source", "events") != "events":
            raise ValidationError({"filters": "MCP subscriptions support captured events. Use source 'events'."})
        if _DERIVED_FILTER_KEYS.intersection(raw_filters):
            raise ValidationError({"filters": "Send event filters without compiled bytecode."})
        serializer = HogFunctionFiltersSerializer(
            data=raw_filters,
            context={
                "get_team": lambda: self.team,
                "function_type": "destination",
                "function_will_be_enabled": True,
                "allow_mcp_event_subscription": True,
            },
        )
        serializer.is_valid(raise_exception=True)
        MCPEventFilterAccessValidator.validate_snapshot(
            serializer.validated_data["mcp_property_dependencies"], team=self.team, user=self.user
        )
        return cast(
            dict[str, JsonValue],
            {key: value for key, value in serializer.validated_data.items() if key not in _DERIVED_FILTER_KEYS},
        )

    def identity(self, filters: dict[str, JsonValue], url: str) -> UUID:
        arguments = json.dumps({"project_id": self.team.pk, "filters": filters}, sort_keys=True, separators=(",", ":"))
        identity = json.dumps([self.principal, MCP_EVENT_NAME, url, arguments], separators=(",", ":"))
        return uuid5(NAMESPACE_URL, hashlib.sha256(identity.encode()).hexdigest())

    def subscribe(
        self,
        *,
        raw_filters: dict[str, JsonValue],
        url: str,
        secret: str,
        credential: str,
        ttl_ms: int | None,
        credential_expires_at: datetime | None,
    ) -> MCPEventSubscription:
        filters = self.normalize_filters(raw_filters)
        subscription_id = self.identity(filters, url)
        now = timezone.now()
        existing = (
            MCPEventSubscription.objects.for_team(self.team.pk)
            .filter(id=subscription_id, created_by=self.user, principal=self.principal)
            .first()
        )
        verified = bool(
            existing
            and existing.active
            and existing.expires_at > now
            and existing.verified_at
            and existing.verified_at > now - timedelta(hours=1)
            and existing.delivery["secret"] == secret
        )
        if not verified:
            verify_callback(subscription_id=str(subscription_id), url=url, secret=secret)

        now = timezone.now()
        if credential_expires_at is not None and credential_expires_at <= now:
            raise PermissionDenied("The subscription credential expired. Reconnect and try again.")
        with transaction.atomic():
            # Serialize project quota admission without locking a busy Team row.
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s, %s)", [0x4D435045, self.team.pk])
            subscription, created = (
                MCPEventSubscription.objects.for_team(self.team.pk)
                .select_for_update()
                .get_or_create(
                    id=subscription_id,
                    defaults={
                        "team_id": self.team.pk,
                        "created_by": self.user,
                        "principal": self.principal,
                        "arguments": {"project_id": self.team.pk, "filters": filters},
                        "delivery": {"url": url, "secret": secret},
                        "expires_at": now,
                    },
                )
            )
            live = (
                MCPEventSubscription.objects.for_team(self.team.pk)
                .filter(active=True, expires_at__gt=now)
                .exclude(id=subscription_id)
            )
            if (
                live.count() >= MAX_SUBSCRIPTIONS_PER_PROJECT
                or live.filter(created_by=self.user).count() >= MAX_SUBSCRIPTIONS_PER_USER
            ):
                raise ValidationError("Subscription limit reached. Stop an existing subscription and try again.")
            if subscription.created_by_id != self.user.pk or subscription.principal != self.principal:
                raise PermissionDenied("This subscription belongs to another account.")
            old_delivery = subscription.delivery
            delivery = {"url": url, "secret": secret}
            if not created and subscription.active and subscription.expires_at > now:
                if old_delivery["secret"] != secret:
                    delivery["previous_secret"] = old_delivery["secret"]
                    delivery["previous_secret_until"] = (now + SECRET_ROTATION_GRACE).isoformat()
                elif old_delivery.get("previous_secret_until"):
                    delivery.update({key: old_delivery[key] for key in ("previous_secret", "previous_secret_until")})
            else:
                subscription.generation = uuid7()
            subscription.delivery = delivery
            subscription.expires_at = now + timedelta(milliseconds=min(ttl_ms or MAX_TTL_MS, MAX_TTL_MS))
            if credential_expires_at is not None:
                subscription.expires_at = min(subscription.expires_at, credential_expires_at)
            if not verified:
                subscription.verified_at = now
            subscription.active = True
            subscription.hog_function = MCPEventDestination.save(
                subscription, credential=credential, team=self.team, user=self.user
            )
            compiled_filters = subscription.hog_function.filters or {}
            MCPEventFilterAccessValidator.validate_snapshot(
                compiled_filters["mcp_property_dependencies"], team=self.team, user=self.user
            )
            subscription.save()
            self._reload_after_commit(subscription)
        return subscription

    def unsubscribe(self, *, raw_filters: dict[str, JsonValue], url: str) -> None:
        parser = HogFunctionFiltersSerializer(context={"get_team": lambda: self.team, "function_type": "destination"})
        filters = parser.to_internal_value(raw_filters)
        with transaction.atomic():
            subscription = (
                MCPEventSubscription.objects.for_team(self.team.pk)
                .select_for_update()
                .filter(id=self.identity(filters, url), created_by=self.user, principal=self.principal)
                .first()
            )
            if subscription is None:
                return
            subscription.active = False
            subscription.generation = uuid7()
            subscription.save(update_fields=["active", "generation", "updated_at"])
            if subscription.hog_function is not None:
                subscription.hog_function.enabled = False
                subscription.hog_function.save(update_fields=["enabled", "updated_at"])
                self._reload_after_commit(subscription)

    @staticmethod
    def _reload_after_commit(subscription: MCPEventSubscription) -> None:
        transaction.on_commit(
            partial(
                reload_hog_functions_on_workers,
                team_id=subscription.team_id,
                hog_function_ids=[str(subscription.hog_function_id)],
            )
        )

    @classmethod
    def expire(cls) -> int:
        # A bounded cross-project sweep discovers work; each mutation uses its own team scope and lock.
        candidates = list(
            MCPEventSubscription.objects.unscoped()
            .filter(active=True, expires_at__lte=timezone.now())
            .order_by("expires_at")
            .values_list("team_id", "id")[:EXPIRY_BATCH_SIZE]
        )
        count = 0
        for team_id, subscription_id in candidates:
            with transaction.atomic():
                subscription = (
                    MCPEventSubscription.objects.for_team(team_id)
                    .select_for_update()
                    .filter(id=subscription_id, active=True, expires_at__lte=timezone.now())
                    .first()
                )
                if subscription is None:
                    continue
                subscription.active = False
                subscription.generation = uuid7()
                subscription.save(update_fields=["active", "generation", "updated_at"])
                if subscription.hog_function is not None:
                    subscription.hog_function.enabled = False
                    subscription.hog_function.save(update_fields=["enabled", "updated_at"])
                    cls._reload_after_commit(subscription)
                count += 1
        if len(candidates) == EXPIRY_BATCH_SIZE:
            expire_mcp_event_subscriptions.delay()
        return count
