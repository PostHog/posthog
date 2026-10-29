import uuid
import hashlib

from rest_framework import serializers

from posthog.api.capture import capture_batch_internal
from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.integrations import IntegrationRecord

DEVICE_SUBSCRIPTION_PREFIX = "$device_push_subscription_"
MAX_SUBSCRIPTIONS_PER_REQUEST = 1000
EVENT_SOURCE = "push_token_import"


class PushTokenSubscriptionSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(max_length=200, help_text="The person's distinct ID in this project.")
    device_token = serializers.CharField(
        max_length=4096, help_text="The APNs device token or FCM registration token of one device."
    )


class PushTokenImportRequestSerializer(serializers.Serializer):
    subscriptions: serializers.ListSerializer = serializers.ListSerializer(
        child=PushTokenSubscriptionSerializer(),
        allow_empty=False,
        max_length=MAX_SUBSCRIPTIONS_PER_REQUEST,
        help_text=f"Up to {MAX_SUBSCRIPTIONS_PER_REQUEST} devices to register on this push channel. "
        "List a person once per device.",
    )


class PushTokenImportResponseSerializer(serializers.Serializer):
    imported = serializers.IntegerField(help_text="Number of devices stored on their person.")
    failed_distinct_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Distinct IDs with at least one device that was not stored. Send those rows again.",
    )


@frozen
class PushTokenImportResult:
    imported: int
    failed_distinct_ids: list[str]


class _TokenCipher(EncryptedFieldMixin):
    pass


def push_channel_app_id(integration: IntegrationRecord) -> str | None:
    if integration.kind == "apns":
        return integration.config.get("bundle_id") or None
    if integration.kind == "firebase":
        return integration.config.get("project_id") or None
    return None


def device_subscription_key(app_id: str, device_token: str) -> str:
    # Must match deviceSubscriptionKey in the Node push sender, which reads these keys back.
    digest = hashlib.sha256(device_token.encode("utf-8")).hexdigest()[:16]
    return f"{DEVICE_SUBSCRIPTION_PREFIX}{app_id}:{digest}"


def import_push_tokens(
    integration: IntegrationRecord, subscriptions: list[dict[str, str]], team_api_token: str
) -> PushTokenImportResult:
    app_id = push_channel_app_id(integration)
    if not app_id:
        raise ValueError("This integration is not a push channel.")

    cipher = _TokenCipher()
    events = []
    distinct_id_by_uuid: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    for subscription in subscriptions:
        distinct_id, device_token = subscription["distinct_id"], subscription["device_token"]
        if (distinct_id, device_token) in seen:
            continue
        seen.add((distinct_id, device_token))
        event_uuid = str(uuid.uuid4())
        distinct_id_by_uuid[event_uuid] = distinct_id
        events.append(
            {
                "event": "$set",
                "distinct_id": distinct_id,
                "event_uuid": event_uuid,
                # Encrypted, because the sender ignores a token it cannot decrypt as forged.
                "properties": {"$set": {device_subscription_key(app_id, device_token): cipher.encrypt(device_token)}},
                "options": {"process_person_profile": True},
            }
        )

    result = capture_batch_internal(
        events=events,
        token=team_api_token,
        event_source=EVENT_SOURCE,
        process_person_profile=True,
    )
    # Capture skips the person update when person processing is disabled, so that device was never stored.
    skipped = {
        event_uuid
        for event_uuid in result.warnings
        if result.results.get(event_uuid, {}).get("details") == "person_processing_disabled"
    }
    failed = {*result.dropped, *result.retried, *result.unaccounted, *skipped}
    return PushTokenImportResult(
        imported=len(events) - len(failed),
        failed_distinct_ids=sorted({distinct_id_by_uuid[event_uuid] for event_uuid in failed}),
    )
