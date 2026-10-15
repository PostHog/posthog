import json
import hashlib
from copy import deepcopy
from datetime import datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Final, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from pydantic import JsonValue
from rest_framework.exceptions import PermissionDenied, ValidationError

from posthog.schema import CachedHogQLQueryResponse, HogQLQuery, HogQLQueryResponse

from posthog.hogql import ast
from posthog.hogql.printer import to_printed_hogql

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.hogql_queries.hogql_query_runner import HogQLQueryRunner
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Team, User
from posthog.models.utils import uuid7
from posthog.plugins.plugin_server_api import reload_hog_functions_on_workers

from products.access_control.backend.facade.api import (
    get_restricted_properties_with_group_type_index_for_team,
    split_restricted_property_names,
)
from products.cdp.backend.filters import compile_filters_expr
from products.cdp.backend.mcp_event_delivery import (
    MCP_CREDENTIAL_INPUT,
    MCP_EVENT_MAX_BYTES,
    MCP_EVENT_NAME,
    signed_headers,
    verify_callback,
)
from products.cdp.backend.mcp_event_filters import MCPEventFilterAccessValidator
from products.cdp.backend.mcp_event_properties import MCPEventPropertyAccess
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.mcp_event_subscription import MCPEventSubscription
from products.cdp.backend.validation import HogFunctionFiltersSerializer

if TYPE_CHECKING:
    from products.cdp.backend.api.hog_function import HogFunctionSerializer

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
            context={"get_team": lambda: self.team, "function_type": "destination", "function_will_be_enabled": True},
        )
        serializer.is_valid(raise_exception=True)
        filters = {key: value for key, value in serializer.validated_data.items() if key not in _DERIVED_FILTER_KEYS}
        expression = compile_filters_expr(filters, self.team)
        MCPEventFilterAccessValidator.validate(expression, team=self.team, user=self.user)
        return cast(dict[str, JsonValue], filters)

    def identity(self, filters: dict[str, JsonValue], url: str) -> UUID:
        arguments = json.dumps({"project_id": self.team.pk, "filters": filters}, sort_keys=True, separators=(",", ":"))
        identity = json.dumps([self.principal, MCP_EVENT_NAME, url, arguments], separators=(",", ":"))
        return uuid5(NAMESPACE_URL, hashlib.sha256(identity.encode()).hexdigest())

    def preview(self, raw_filters: dict[str, JsonValue]) -> dict[str, JsonValue]:
        filters = self.normalize_filters(raw_filters)
        expression = compile_filters_expr(filters, self.team)
        cutoff = timezone.now() - timedelta(days=7)
        query = ast.SelectQuery(
            select=[ast.Field(chain=[field]) for field in ("uuid", "event", "distinct_id", "timestamp", "properties")],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    expression,
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Gt,
                        left=ast.Field(chain=["timestamp"]),
                        right=ast.Constant(value=cutoff),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            limit=ast.Constant(value=5),
        )
        with tags_context(product=Product.PIPELINE_DESTINATIONS, feature=Feature.QUERY, api_queries_budgeted=True):
            runner = HogQLQueryRunner(
                query=HogQLQuery(query=to_printed_hogql(query, self.team)), team=self.team, user=self.user
            )
            runner.is_query_service = True
            result = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS, user=self.user)
            assert isinstance(result, (HogQLQueryResponse, CachedHogQLQueryResponse))
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=self.user, team_id=self.team.pk)
        restricted_event_properties = split_restricted_property_names(restrictions).event
        examples: list[JsonValue] = []
        for row in result.results or []:
            properties = json.loads(row[4]) if isinstance(row[4], str) else row[4]
            if not isinstance(properties, dict):
                properties = {}
            examples.append(
                {
                    "eventId": str(row[0]),
                    "name": MCP_EVENT_NAME,
                    "timestamp": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
                    "data": {
                        "event": str(row[1]),
                        "distinct_id": str(row[2]),
                        "properties": MCPEventPropertyAccess.redact(properties, set(restricted_event_properties)),
                    },
                    "cursor": None,
                }
            )
        return {"filters": filters, "examples": examples, "lookback_days": 7, "sample_limit": 5}

    def _save_destination(
        self, subscription: MCPEventSubscription, credential: str, serializer_class: type["HogFunctionSerializer"]
    ) -> None:
        template = HogFunctionTemplate.get_template("template-webhook")
        if template is None:
            raise ValidationError("The webhook destination is unavailable. Sync destination templates and try again.")
        code = template.code.replace("fetch(", "mcpEventFetch(")
        if code == template.code:
            raise ValidationError(
                "The webhook destination cannot be used for MCP events. Sync templates and try again."
            )
        schema = deepcopy(template.inputs_schema)
        for item in schema:
            if item["key"] == "url":
                item["secret"] = True
        schema.extend(
            [
                {
                    "key": MCP_CREDENTIAL_INPUT,
                    "type": "string",
                    "secret": True,
                    "required": True,
                    "label": "Subscription credential",
                },
                {"key": "mcp_generation", "type": "string", "required": True, "label": "Subscription generation"},
            ]
        )
        payload = {
            "name": "MCP event subscription",
            "description": "Delivers matching captured events to the subscribing MCP client.",
            "template_id": "template-webhook",
            "type": "destination",
            "enabled": True,
            "hog": code,
            "inputs_schema": schema,
            "filters": subscription.arguments["filters"],
            "inputs": {
                "url": {"value": subscription.delivery["url"]},
                "method": {"value": "POST"},
                "debug": {"value": False},
                "signing_secret": {"value": subscription.delivery["secret"]},
                MCP_CREDENTIAL_INPUT: {"value": credential},
                "mcp_generation": {"value": str(subscription.generation)},
                "headers": {
                    "value": {"Content-Type": "application/json", "X-MCP-Subscription-Id": str(subscription.pk)}
                },
                "body": {
                    "value": {
                        "eventId": "{event.uuid}",
                        "name": MCP_EVENT_NAME,
                        "timestamp": "{event.timestamp}",
                        "data": {
                            "event": "{event.event}",
                            "distinct_id": "{event.distinct_id}",
                            "properties": "{event.properties}",
                        },
                        "cursor": None,
                    }
                },
            },
        }
        serializer = serializer_class(
            instance=subscription.hog_function,
            data=payload,
            context={
                "get_team": lambda: self.team,
                "is_create": subscription.hog_function_id is None,
                "allow_mcp_event_subscription": True,
                "function_type": "destination",
            },
        )
        serializer.is_valid(raise_exception=True)
        subscription.hog_function = serializer.save(team=self.team, created_by=self.user)
        compiled_filters = subscription.hog_function.filters or {}
        MCPEventFilterAccessValidator.validate_snapshot(
            compiled_filters["mcp_property_dependencies"], team=self.team, user=self.user
        )
        subscription.delivery["filter_bytecode"] = deepcopy(compiled_filters["bytecode"])
        subscription.delivery["filter_dependencies"] = deepcopy(compiled_filters["mcp_property_dependencies"])

    def subscribe(
        self,
        *,
        raw_filters: dict[str, JsonValue],
        url: str,
        secret: str,
        credential: str,
        ttl_ms: int | None,
        credential_expires_at: datetime | None,
        serializer_class: type["HogFunctionSerializer"],
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
            self._save_destination(subscription, credential, serializer_class)
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
            .values_list("team_id", "id")[:500]
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
        return count

    def authorize_delivery(
        self,
        *,
        subscription: MCPEventSubscription,
        generation: str,
        body: str,
        url: str,
        function_id: str,
        filter_bytecode: list[JsonValue],
    ) -> dict[str, JsonValue]:
        if (
            not subscription.active
            or subscription.expires_at <= timezone.now()
            or str(subscription.generation) != generation
            or subscription.delivery["url"] != url
            or str(subscription.hog_function_id) != function_id
        ):
            raise PermissionDenied("This subscription is no longer active.")
        if filter_bytecode != subscription.delivery.get("filter_bytecode"):
            raise PermissionDenied("The queued filter has changed. Renew the subscription.")
        dependencies = subscription.delivery.get("filter_dependencies")
        if not isinstance(dependencies, dict):
            raise PermissionDenied("Renew the subscription before delivering events.")
        MCPEventFilterAccessValidator.validate_snapshot(dependencies, team=self.team, user=self.user)
        if len(body.encode()) > MCP_EVENT_MAX_BYTES:
            raise ValidationError("The event exceeds the 256 KiB delivery limit.")
        try:
            event = json.loads(body)
        except ValueError:
            raise ValidationError("Send a valid JSON event envelope.") from None
        if (
            not isinstance(event, dict)
            or event.get("name") != MCP_EVENT_NAME
            or not isinstance(event.get("eventId"), str)
            or not event["eventId"]
            or len(event["eventId"]) > 255
            or set(event) != {"eventId", "name", "timestamp", "data", "cursor"}
            or event.get("cursor") is not None
        ):
            raise ValidationError("Send a captured PostHog event envelope with an event ID.")
        data = event.get("data")
        if (
            not isinstance(data, dict)
            or set(data) != {"event", "distinct_id", "properties"}
            or not isinstance(data.get("event"), str)
            or not isinstance(data.get("distinct_id"), str)
            or not isinstance(data.get("properties"), dict)
        ):
            raise ValidationError("The event payload must include an event properties object.")
        timestamp = event.get("timestamp")
        try:
            parsed_timestamp = parse_datetime(timestamp) if isinstance(timestamp, str) else None
        except ValueError:
            parsed_timestamp = None
        if parsed_timestamp is None or timezone.is_naive(parsed_timestamp):
            raise ValidationError("The event timestamp must include a timezone.")
        restrictions = get_restricted_properties_with_group_type_index_for_team(user=self.user, team_id=self.team.pk)
        restricted_names = split_restricted_property_names(restrictions).event
        data["properties"] = MCPEventPropertyAccess.redact(data["properties"], set(restricted_names))
        try:
            serialized = json.dumps(event, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except ValueError:
            raise ValidationError("Event properties must contain valid JSON values.") from None
        if len(serialized.encode()) > MCP_EVENT_MAX_BYTES:
            raise ValidationError("The event exceeds the 256 KiB delivery limit.")
        headers = signed_headers(
            subscription_id=str(subscription.pk),
            webhook_id=event["eventId"],
            body=serialized,
            secret=subscription.delivery["secret"],
        )
        previous_secret_until = subscription.delivery.get("previous_secret_until")
        if previous_secret_until and timezone.now() < datetime.fromisoformat(previous_secret_until):
            old_headers = signed_headers(
                subscription_id=str(subscription.pk),
                webhook_id=event["eventId"],
                body=serialized,
                secret=subscription.delivery["previous_secret"],
                signed_at=int(headers["webhook-timestamp"]),
            )
            headers["webhook-signature"] += " " + old_headers["webhook-signature"]
        return {"body": serialized, "headers": cast(dict[str, JsonValue], headers)}
