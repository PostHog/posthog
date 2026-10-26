import json
import math
import time
import uuid
import hashlib
from datetime import timedelta
from typing import cast

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import JsonValue

from posthog.constants import AvailableFeature
from posthog.event_usage import report_organization_action
from posthog.models import Organization
from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFEvent, SSFStream
from posthog.ssf.remote import SSFRemote
from posthog.ssf.validation import (
    CONTROL_EVENTS,
    MAX_TOKEN_BYTES,
    POLL_DELIVERY,
    RETENTION_DAYS,
    STREAM_UPDATED_EVENT,
    VERIFICATION_EVENT,
    SSFOutgoingEventType,
    is_event_type,
    subjects_match,
    validate_subject,
)


class SETValidationError(ValueError):
    def __init__(self, code: str, description: str):
        self.code = code
        super().__init__(description)


class SSFService:
    @staticmethod
    def is_enabled(config: SSFConfiguration) -> bool:
        return bool(
            config.enabled
            and config.organization.is_active
            and config.organization.is_feature_available(AvailableFeature.SSF)
        )

    @staticmethod
    def is_connection_enabled(config: SSFConfiguration, connection: SSFConnection) -> bool:
        return (
            connection.organization_id == config.organization_id
            and connection.enabled
            and SSFService.is_enabled(config)
        )

    @staticmethod
    def issuer(organization: Organization) -> str:
        return f"{settings.SITE_URL.rstrip('/')}/ssf/{organization.id}"

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @staticmethod
    @sensitive_variables("private_key")
    def rotate_signing_key(config: SSFConfiguration) -> None:
        cutoff = time.time() - RETENTION_DAYS * 86400 - 300
        config.previous_public_keys = [entry for entry in config.previous_public_keys if entry["retired_at"] > cutoff]
        if config.signing_key:
            config.previous_public_keys.append({"key": SSFService.public_key(config), "retired_at": int(time.time())})
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        config.signing_key = private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode()
        config.signing_key_id = uuid.uuid4().hex

    @staticmethod
    def public_key(config: SSFConfiguration) -> dict[str, JsonValue]:
        key = serialization.load_pem_private_key(config.signing_key.encode(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError("SSF signing keys must be RSA private keys.")
        return {
            **jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True),
            "kid": config.signing_key_id,
            "use": "sig",
            "alg": "RS256",
        }

    @staticmethod
    def public_keys(config: SSFConfiguration) -> list[dict[str, JsonValue]]:
        cutoff = time.time() - RETENTION_DAYS * 86400 - 300
        return [
            SSFService.public_key(config),
            *(entry["key"] for entry in config.previous_public_keys if entry["retired_at"] > cutoff),
        ]

    @staticmethod
    def supported_event_types(config: SSFConfiguration) -> list[str]:
        selected = set(config.event_types)
        return [*CONTROL_EVENTS, *(event for event in SSFOutgoingEventType.values if event in selected)]

    @staticmethod
    def stream_configuration(config: SSFConfiguration, stream: SSFStream) -> dict[str, JsonValue]:
        issuer = SSFService.issuer(config.organization)
        supported = SSFService.supported_event_types(config)
        return {
            "stream_id": str(stream.id),
            "iss": issuer,
            "aud": stream.audiences or [stream.audience],
            "events_supported": supported,
            "events_requested": stream.events_requested,
            "events_delivered": [event for event in stream.events_requested if event in supported],
            "delivery": {"method": POLL_DELIVERY, "endpoint_url": f"{issuer}/poll/{stream.id}"},
            "description": stream.description,
        }

    @staticmethod
    def create_outgoing_stream(
        config: SSFConfiguration, connection: SSFConnection, events_requested: list[str], description: str
    ) -> SSFStream:
        if (
            connection.organization_id != config.organization_id
            or connection.direction != SSFConnection.Direction.OUTGOING
        ):
            raise ValueError("Select an outgoing connection from this organization.")
        with transaction.atomic():
            SSFConfiguration.objects.select_for_update().get(organization=config.organization, pk=config.pk)
            if SSFStream.objects.filter(organization=config.organization, connection=connection).count() >= 100:
                raise ValueError(
                    "This connection has reached its 100-stream limit. Delete an unused stream and try again."
                )
            supported = SSFService.supported_event_types(config)
            stream = SSFStream(
                organization=config.organization,
                connection=connection,
                audience=connection.audience,
                audiences=[connection.audience],
                events_requested=events_requested,
                events_delivered=[event for event in events_requested if event in supported],
                description=description,
            )
            stream.endpoint_url = f"{SSFService.issuer(config.organization)}/poll/{stream.id}"
            stream.save()
        report_organization_action(config.organization, "ssf stream created", {"direction": "outgoing"})
        return stream

    @staticmethod
    def update_outgoing_stream(
        config: SSFConfiguration,
        stream: SSFStream,
        *,
        description: str | None = None,
        events_requested: list[str] | None = None,
    ) -> SSFStream:
        with transaction.atomic():
            stream = SSFService._lock_stream(config, stream)
            if description is not None:
                stream.description = description
            if events_requested is not None:
                stream.events_requested = events_requested
            supported = SSFService.supported_event_types(config)
            stream.events_delivered = [event for event in stream.events_requested if event in supported]
            stream.save(update_fields=["description", "events_requested", "events_delivered"])
        return stream

    @staticmethod
    @sensitive_variables("token", "subject", "payload")
    def _queue(
        config: SSFConfiguration,
        stream: SSFStream,
        event_type: str,
        subject: dict[str, JsonValue],
        payload: dict[str, JsonValue],
        *,
        txn: str,
    ) -> SSFEvent:
        # The stream lock serializes producers so an unpolled stream cannot grow without bound.
        if SSFEvent.objects.filter(organization=config.organization, stream=stream).count() >= 10000:
            raise ValueError("The SSF stream queue is full. Poll and acknowledge pending events before producing more.")
        jti = uuid.uuid4().hex
        issuer = SSFService.issuer(config.organization)
        token = jwt.encode(
            {
                "iss": issuer,
                "aud": stream.audiences or [stream.audience],
                "jti": jti,
                "iat": int(time.time()),
                "txn": txn,
                "sub_id": subject,
                "events": {event_type: payload},
            },
            config.signing_key,
            algorithm="RS256",
            headers={"typ": "secevent+jwt", "kid": config.signing_key_id},
        )
        if len(token.encode()) > MAX_TOKEN_BYTES:
            raise ValueError("The security event token exceeds the 64 KiB limit.")
        event = SSFEvent.objects.create(
            organization=config.organization,
            stream=stream,
            direction=SSFEvent.Direction.OUTGOING,
            issuer_hash=SSFService.token_hash(issuer),
            jti=jti,
            token=token,
        )
        transaction.on_commit(
            lambda: report_organization_action(config.organization, "ssf event produced", {"event_type": event_type}),
            robust=True,
        )
        return event

    @staticmethod
    @sensitive_variables("subject", "payload")
    def produce_event(
        organization: Organization,
        event_type: str,
        subject: dict[str, JsonValue],
        payload: dict[str, JsonValue],
        *,
        txn: str | None = None,
    ) -> int:
        validate_subject(subject)
        if not is_event_type(event_type):
            raise ValueError("The event type must be a URI.")
        config = SSFConfiguration.objects.filter(organization=organization, enabled=True).first()
        if not config or not SSFService.is_enabled(config):
            return 0
        if event_type not in SSFService.supported_event_types(config):
            raise ValueError("The event type is not configured for this organization.")
        transaction_id = txn or uuid.uuid4().hex
        count = 0
        with transaction.atomic():
            for stream in (
                SSFStream.objects.select_for_update(of=("self",))
                .select_related("connection")
                .filter(
                    organization=organization,
                    connection__organization=organization,
                    connection__enabled=True,
                    connection__direction=SSFConnection.Direction.OUTGOING,
                )
                .filter(status__in=[SSFStream.Status.ENABLED, SSFStream.Status.PAUSED])
                .order_by("id")
            ):
                if event_type in CONTROL_EVENTS:
                    if subject != {"format": "opaque", "id": str(stream.id)}:
                        continue
                elif event_type not in stream.events_requested or not any(
                    subjects_match(subject, candidate) for candidate in json.loads(stream.subjects)
                ):
                    continue
                SSFService._queue(config, stream, event_type, subject, payload, txn=transaction_id)
                count += 1
        return count

    @staticmethod
    def request_verification(config: SSFConfiguration, stream: SSFStream, state: str | None) -> None:
        connection = stream.connection
        if connection is None or connection.direction != SSFConnection.Direction.OUTGOING:
            raise ValueError("This operation requires an outgoing stream.")
        with transaction.atomic():
            stream = SSFService._lock_stream(config, stream)
            if stream.status == SSFStream.Status.DISABLED:
                raise ValueError("Enable the stream before requesting verification.")
            SSFService._queue(
                config,
                stream,
                VERIFICATION_EVENT,
                {"format": "opaque", "id": str(stream.id)},
                {"state": state} if state is not None else {},
                txn=uuid.uuid4().hex,
            )

    @staticmethod
    def _lock_stream(config: SSFConfiguration, stream: SSFStream) -> SSFStream:
        if not SSFService.is_enabled(config):
            raise SSFStream.DoesNotExist("SSF transmission is not enabled.")
        return SSFStream.objects.select_for_update().get(
            organization=config.organization,
            connection__organization=config.organization,
            connection__enabled=True,
            connection__direction=SSFConnection.Direction.OUTGOING,
            connection_id=stream.connection_id,
            pk=stream.pk,
        )

    @staticmethod
    def set_status_from_receiver(config: SSFConfiguration, stream: SSFStream, status: str, reason: str) -> SSFStream:
        if status not in (SSFStream.Status.ENABLED, SSFStream.Status.PAUSED, SSFStream.Status.DISABLED):
            raise ValueError("The stream status is invalid.")
        with transaction.atomic():
            stream = SSFService._lock_stream(config, stream)
            stream.status = status
            stream.reason = reason
            stream.save(update_fields=["status", "reason"])
            if stream.status == SSFStream.Status.DISABLED:
                SSFEvent.objects.filter(organization=config.organization, stream=stream).delete()
        return stream

    @staticmethod
    def update_subject(
        config: SSFConfiguration, stream: SSFStream, subject: dict[str, JsonValue], *, remove: bool
    ) -> None:
        validate_subject(subject)
        with transaction.atomic():
            stream = SSFService._lock_stream(config, stream)
            subjects = json.loads(stream.subjects)
            if subject == {"format": "opaque", "id": str(stream.id)}:
                if remove:
                    raise ValueError("The stream's implicit subject cannot be removed.")
            elif remove:
                subjects = [candidate for candidate in subjects if candidate != subject]
            elif subject not in subjects:
                if len(subjects) >= 1000:
                    raise ValueError("Remove an unused subject before adding more than 1000 subjects.")
                subjects.append(subject)
            stream.subjects = json.dumps(subjects)
            stream.save(update_fields=["subjects"])

    @staticmethod
    def _pending_events(config: SSFConfiguration, stream: SSFStream) -> QuerySet[SSFEvent]:
        return SSFEvent.objects.filter(
            organization=config.organization,
            stream=stream,
            created_at__gte=timezone.now() - timedelta(days=RETENTION_DAYS),
        ).order_by("created_at", "id")

    @staticmethod
    @sensitive_variables("events", "selected")
    def poll_stream(
        config: SSFConfiguration,
        stream: SSFStream,
        *,
        max_events: int,
        return_immediately: bool,
        acknowledged: list[str],
    ) -> dict[str, JsonValue]:
        SSFService.delete_expired_events(config.organization)
        with transaction.atomic():
            stream = SSFService._lock_stream(config, stream)
            SSFService._pending_events(config, stream).filter(
                jti__in=acknowledged, first_delivered_at__isnull=False
            ).delete()
        # ponytail: synchronous long polls hold a web worker; use async delivery if polling volume grows.
        timeout = getattr(settings, "SSF_POLL_TIMEOUT_SECONDS", 5)
        deadline = time.monotonic() + (0 if return_immediately else timeout)
        while True:
            with transaction.atomic():
                stream = SSFService._lock_stream(config, stream)
                if stream.status == SSFStream.Status.ENABLED:
                    limit = min(max_events, 100)
                    events = list(SSFService._pending_events(config, stream)[: limit + 1])
                    selected = events[:limit]
                    if events or time.monotonic() >= deadline:
                        SSFService._pending_events(config, stream).filter(
                            id__in=[event.id for event in selected], first_delivered_at__isnull=True
                        ).update(first_delivered_at=timezone.now())
                        return {
                            "sets": {event.jti: event.token for event in selected},
                            "moreAvailable": len(events) > limit,
                        }
                elif time.monotonic() >= deadline:
                    return {"sets": {}, "moreAvailable": False}
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))

    @staticmethod
    @sensitive_variables("token", "claims")
    def validate_token(stream: SSFStream, token: str) -> dict[str, JsonValue]:
        connection = stream.connection
        if connection is None or connection.direction != SSFConnection.Direction.INCOMING or not stream.audiences:
            raise SETValidationError("access_denied", "The incoming stream is not configured.")
        try:
            if not isinstance(token, str) or not token:
                raise SETValidationError("invalid_request", "The request must contain a security event token.")
            if len(token.encode()) > MAX_TOKEN_BYTES:
                raise SETValidationError("invalid_request", "The security event token exceeds the 64 KiB limit.")
            header = jwt.get_unverified_header(token)
            if header.get("typ") != "secevent+jwt" or header.get("alg") not in ("RS256", "ES256") or "crit" in header:
                raise SETValidationError(
                    "invalid_request", "Use an RS256 or ES256 security event token with explicit typing."
                )
            key = SSFRemote.select_key(connection, header)
            try:
                claims = jwt.decode(
                    token,
                    key.key,
                    algorithms=[header["alg"]],
                    issuer=connection.issuer,
                    audience=connection.audience or stream.audiences,
                    options={"require": ["iss", "aud", "iat", "jti", "events", "sub_id"]},
                    leeway=300,
                )
            except jwt.InvalidSignatureError:
                key = SSFRemote.select_key(connection, header, refresh=True)
                claims = jwt.decode(
                    token,
                    key.key,
                    algorithms=[header["alg"]],
                    issuer=connection.issuer,
                    audience=connection.audience or stream.audiences,
                    options={"require": ["iss", "aud", "iat", "jti", "events", "sub_id"]},
                    leeway=300,
                )
        except jwt.InvalidIssuerError as error:
            raise SETValidationError(
                "invalid_issuer", "The issuer does not match the configured transmitter."
            ) from error
        except jwt.InvalidAudienceError as error:
            raise SETValidationError("invalid_audience", "The audience does not match this receiver.") from error
        except (jwt.InvalidSignatureError, jwt.InvalidKeyError) as error:
            raise SETValidationError("invalid_key", "The token signature is invalid.") from error
        except (jwt.PyJWTError, ValueError, TypeError, OverflowError) as error:
            if isinstance(error, SETValidationError):
                raise
            raise SETValidationError("invalid_request", "The security event token is invalid.") from error
        if "sub" in claims or "exp" in claims:
            raise SETValidationError("invalid_request", "SSF tokens must not contain sub or exp claims.")
        issued_at = claims["iat"]
        if (
            type(issued_at) not in (int, float)
            or issued_at < time.time() - RETENTION_DAYS * 86400
            or issued_at > time.time() + 300
            or not math.isfinite(issued_at)
        ):
            raise SETValidationError("invalid_request", "The token issue time is outside the accepted window.")
        if not isinstance(claims["jti"], str) or not 1 <= len(claims["jti"]) <= 255:
            raise SETValidationError(
                "invalid_request", "The token must contain a nonempty token ID of at most 255 characters."
            )
        events = claims["events"]
        if (
            not isinstance(events, dict)
            or len(events) != 1
            or not all(isinstance(value, dict) for value in events.values())
            or not all(is_event_type(event_type) for event_type in events)
        ):
            raise SETValidationError(
                "invalid_request", "The events claim must contain one event object with an event type URI."
            )
        try:
            validate_subject(claims["sub_id"], critical_members=connection.metadata.get("critical_subject_members", []))
        except ValueError as error:
            raise SETValidationError("invalid_request", str(error)) from error
        for event_type, payload in events.items():
            if event_type in CONTROL_EVENTS:
                if claims["sub_id"] != {"format": "opaque", "id": stream.remote_stream_id}:
                    raise SETValidationError(
                        "invalid_request", "The control event subject does not match the configured stream."
                    )
            if event_type == VERIFICATION_EVENT:
                expected_state = stream.verification_state
                if payload.get("state") != expected_state and ("state" in payload or expected_state is not None):
                    raise SETValidationError(
                        "invalid_state", "The verification state does not match the expected value."
                    )
            if event_type == STREAM_UPDATED_EVENT and payload.get("status") not in (
                SSFStream.Status.ENABLED,
                SSFStream.Status.PAUSED,
                SSFStream.Status.DISABLED,
            ):
                raise SETValidationError("invalid_request", "The stream status is invalid.")
        return cast(dict[str, JsonValue], claims)

    @staticmethod
    @sensitive_variables("token", "claims")
    def consume_event(config: SSFConfiguration, stream: SSFStream, token: str) -> bool:
        connection = stream.connection
        if (
            connection is None
            or stream.organization_id != config.organization_id
            or not SSFService.is_connection_enabled(config, connection)
        ):
            raise SETValidationError("access_denied", "SSF reception is not enabled for this connection.")
        claims = SSFService.validate_token(stream, token)
        events = cast(dict[str, dict[str, JsonValue]], claims["events"])
        event_type, payload = next(iter(events.items()))
        with transaction.atomic():
            _, created = SSFEvent.objects.get_or_create(
                organization=config.organization,
                direction=SSFEvent.Direction.INCOMING,
                issuer_hash=SSFService.token_hash(connection.issuer),
                jti=claims["jti"],
                defaults={"token": token, "stream": stream},
            )
            if created and event_type == VERIFICATION_EVENT:
                SSFStream.objects.filter(organization=config.organization, pk=stream.pk).update(
                    last_verified_at=timezone.now(), last_error=""
                )
            if created and event_type == STREAM_UPDATED_EVENT:
                reason = payload.get("reason", "")
                SSFStream.objects.filter(organization=config.organization, pk=stream.pk).update(
                    status=payload["status"], reason=reason[:1024] if isinstance(reason, str) else ""
                )
            if created:
                transaction.on_commit(
                    lambda: report_organization_action(
                        config.organization, "ssf event consumed", {"event_type": event_type}
                    ),
                    robust=True,
                )
        return created

    @staticmethod
    def delete_expired_events(organization: Organization) -> None:
        expired = SSFEvent.objects.filter(
            organization=organization, created_at__lt=timezone.now() - timedelta(days=RETENTION_DAYS, minutes=5)
        ).values_list("id", flat=True)[:1000]
        SSFEvent.objects.filter(organization=organization, id__in=list(expired)).delete()
