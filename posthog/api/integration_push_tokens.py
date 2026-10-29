import re
import uuid
import hashlib

from django.db import models

from rest_framework import serializers

from posthog.api.capture import capture_batch_internal
from posthog.dataclasses import frozen
from posthog.helpers.encrypted_fields import EncryptedFieldMixin
from posthog.integrations import IntegrationRecord
from posthog.models.person.util import get_person_uuids_and_matched_distinct_ids

DEVICE_SUBSCRIPTION_PREFIX = "$device_push_subscription_"
MAX_SUBSCRIPTIONS_PER_REQUEST = 1000
EVENT_SOURCE = "push_token_import"
TOKEN_SUFFIX_LENGTH = 6

# Expo tokens address Expo's own push service, so neither APNs nor FCM accepts them.
_EXPO_TOKEN = re.compile(r"^Expo(nent)?PushToken\[.*\]$")
# The iOS SDK hex-encodes the APNs device token. Apple documents the token as variable length,
# so an APNs channel only checks the alphabet.
_HEX_TOKEN = re.compile(r"^(?:[0-9a-fA-F]{2})+$")
_APNS_TOKEN_MIN_HEX_LENGTH = 64


class PushTokenImportFailureReason(models.TextChoices):
    UNKNOWN_PERSON = "unknown_person", "No person has this distinct ID"
    TOKEN_MISMATCH = "token_mismatch", "The token does not fit this channel"
    NOT_STORED = "not_stored", "The device was not stored"
    PERSON_PROCESSING_DISABLED = "person_processing_disabled", "Person processing is off for this person"


class PushTokenSubscriptionSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(
        max_length=200,
        help_text="The person's distinct ID in this project: the ID your app passes to `identify`.",
    )
    device_token = serializers.CharField(
        max_length=4096,
        help_text="The token of one device. An APNs channel takes the hex APNs device token. "
        "A Firebase channel takes the FCM registration token. Expo push tokens are not accepted.",
    )


class PushTokenImportRequestSerializer(serializers.Serializer):
    subscriptions: serializers.ListSerializer = serializers.ListSerializer(
        child=PushTokenSubscriptionSerializer(),
        allow_empty=False,
        max_length=MAX_SUBSCRIPTIONS_PER_REQUEST,
        help_text=f"Up to {MAX_SUBSCRIPTIONS_PER_REQUEST} devices to register on this push channel. "
        "List a person once per device.",
    )
    dry_run = serializers.BooleanField(
        default=False,
        help_text="Check every row and report what would fail, without storing anything. "
        "Run this first and fix the failed rows before importing.",
    )
    create_missing_persons = serializers.BooleanField(
        default=False,
        help_text="Create a person for a distinct ID that has none. Off by default, because a distinct ID "
        "that does not match your app's identify call creates a person that never gets a push.",
    )


class PushTokenImportFailureSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(help_text="The distinct ID of the row.")
    device_token_suffix = serializers.CharField(
        help_text=f"The last {TOKEN_SUFFIX_LENGTH} characters of the row's device token, to find the row."
    )
    reason = serializers.ChoiceField(
        choices=PushTokenImportFailureReason.choices,
        help_text="Why the device was not stored. `unknown_person`: no person has this distinct ID, so check "
        "the ID or set `create_missing_persons`. `token_mismatch`: the token is the wrong kind for this channel, "
        "for example an Expo token, or an APNs token on a Firebase channel. `not_stored` and "
        "`person_processing_disabled`: ingestion did not store the device.",
    )
    detail = serializers.CharField(help_text="A sentence a person can act on.")


class PushTokenImportResponseSerializer(serializers.Serializer):
    imported = serializers.IntegerField(
        help_text="Number of devices stored on their person. On a dry run, the number that would be stored."
    )
    dry_run = serializers.BooleanField(help_text="True when nothing was stored.")
    failed = PushTokenImportFailureSerializer(many=True, help_text="One entry per device that was not stored.")
    failed_distinct_ids = serializers.ListField(
        child=serializers.CharField(),
        help_text="Distinct IDs with at least one device that was not stored. Prefer `failed`, which says why.",
    )


@frozen
class PushTokenImportFailure:
    distinct_id: str
    device_token_suffix: str
    reason: PushTokenImportFailureReason
    detail: str


@frozen
class PushTokenImportResult:
    imported: int
    dry_run: bool
    failed: list[PushTokenImportFailure]

    @property
    def failed_distinct_ids(self) -> list[str]:
        return sorted({failure.distinct_id for failure in self.failed})


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


def token_mismatch(kind: str, device_token: str) -> str | None:
    """Says why a token cannot work on this kind of channel. Rejects only shapes that cannot fit."""
    if _EXPO_TOKEN.match(device_token):
        return "This is an Expo push token. Import the device's APNs or FCM token instead."
    is_hex = bool(_HEX_TOKEN.match(device_token))
    if kind == "apns" and not is_hex:
        return "An APNs channel needs the hex APNs device token. This looks like an FCM or other token."
    if kind == "firebase" and is_hex and len(device_token) >= _APNS_TOKEN_MIN_HEX_LENGTH:
        return "This looks like an APNs device token. Import it into an APNs channel instead."
    return None


def import_push_tokens(
    integration: IntegrationRecord,
    subscriptions: list[dict[str, str]],
    team_api_token: str,
    *,
    dry_run: bool = False,
    create_missing_persons: bool = False,
) -> PushTokenImportResult:
    app_id = push_channel_app_id(integration)
    if not app_id:
        raise ValueError("This integration is not a push channel.")

    failed: list[PushTokenImportFailure] = []

    def fail(row: tuple[str, str], reason: PushTokenImportFailureReason, detail: str) -> None:
        failed.append(
            PushTokenImportFailure(
                distinct_id=row[0], device_token_suffix=row[1][-TOKEN_SUFFIX_LENGTH:], reason=reason, detail=detail
            )
        )

    rows: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for subscription in subscriptions:
        row = (subscription["distinct_id"], subscription["device_token"])
        if row in seen:
            continue
        seen.add(row)
        if mismatch := token_mismatch(integration.kind, row[1]):
            fail(row, PushTokenImportFailureReason.TOKEN_MISMATCH, mismatch)
        else:
            rows.append(row)

    if rows and not create_missing_persons:
        _, known = get_person_uuids_and_matched_distinct_ids(integration.team_id, sorted({d for d, _ in rows}))
        for row in rows:
            if row[0] not in known:
                fail(
                    row,
                    PushTokenImportFailureReason.UNKNOWN_PERSON,
                    "No person has this distinct ID. Use the ID your app passes to identify, "
                    "or import with create_missing_persons.",
                )
        rows = [row for row in rows if row[0] in known]

    if dry_run or not rows:
        return PushTokenImportResult(imported=len(rows), dry_run=dry_run, failed=failed)

    cipher = _TokenCipher()
    events = []
    row_by_uuid: dict[str, tuple[str, str]] = {}
    for distinct_id, device_token in rows:
        event_uuid = str(uuid.uuid4())
        row_by_uuid[event_uuid] = (distinct_id, device_token)
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
    skipped = [
        event_uuid
        for event_uuid in result.warnings
        if result.results.get(event_uuid, {}).get("details") == "person_processing_disabled"
    ]
    not_stored = [
        event_uuid
        for event_uuid in (*result.dropped, *result.retried, *result.unaccounted)
        if event_uuid not in skipped
    ]
    for event_uuid in skipped:
        fail(
            row_by_uuid[event_uuid],
            PushTokenImportFailureReason.PERSON_PROCESSING_DISABLED,
            "Person processing is off for this person, so the device was not stored.",
        )
    for event_uuid in not_stored:
        fail(
            row_by_uuid[event_uuid],
            PushTokenImportFailureReason.NOT_STORED,
            "Ingestion did not store this device. Send the row again.",
        )
    return PushTokenImportResult(imported=len(events) - len(skipped) - len(not_stored), dry_run=False, failed=failed)
