import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from django.db.models import Q
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from pydantic import JsonValue

from posthog.event_usage import report_organization_action
from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFEvent, SSFStream
from posthog.ssf.remote import SSFRemote, SSFRemoteError
from posthog.ssf.service import SSFService
from posthog.ssf.validation import PUSH_DELIVERY


class SSFOperationInProgress(ValueError):
    pass


class SSFProvisioning:
    @staticmethod
    def record_error(stream: SSFStream, error: SSFRemoteError) -> None:
        stream.last_error = str(error)[:1024]
        if error.retry_after is not None:
            try:
                stream.retry_at = timezone.now() + timedelta(seconds=max(1, error.retry_after))
            except OverflowError:
                stream.retry_at = datetime.max.replace(tzinfo=UTC)
        stream.save(update_fields=["last_error", "retry_at"])

    @staticmethod
    def refresh_connection(connection: SSFConnection, *, force: bool = False) -> SSFConnection:
        if connection.direction != SSFConnection.Direction.INCOMING:
            raise ValueError("Only incoming connections discover a remote transmitter.")
        metadata = SSFRemote.discover(connection, force=force)
        connection.jwks_uri = cast(str, metadata["jwks_uri"])
        SSFRemote.keys(connection, refresh=force)
        connection.metadata = metadata
        connection.legacy_jwks = {}
        connection.discovered_at = timezone.now()
        return connection

    @staticmethod
    def endpoint(connection: SSFConnection, name: str) -> str:
        endpoint = connection.metadata.get(name)
        if not isinstance(endpoint, str) or not endpoint:
            raise SSFRemoteError("The transmitter does not advertise this stream management operation.")
        return endpoint

    @staticmethod
    def _require_incoming(config: SSFConfiguration, stream: SSFStream) -> SSFConnection:
        connection = stream.connection
        if (
            stream.organization_id != config.organization_id
            or connection is None
            or connection.direction != SSFConnection.Direction.INCOMING
        ):
            raise ValueError("Select an incoming stream from this organization.")
        return connection

    @staticmethod
    @contextmanager
    def operation(stream: SSFStream) -> Iterator[None]:
        deadline = timezone.now() + timedelta(minutes=5)
        claimed = (
            SSFStream.objects.filter(organization=stream.organization, pk=stream.pk)
            .filter(Q(operation_until__isnull=True) | Q(operation_until__lt=timezone.now()))
            .filter(Q(retry_at__isnull=True) | Q(retry_at__lte=timezone.now()))
            .update(operation_until=deadline)
        )
        if not claimed:
            stream.refresh_from_db(fields=["retry_at"])
            if stream.retry_at and stream.retry_at > timezone.now():
                raise SSFRemoteError(
                    "The transmitter is rate limiting this stream. Try again later.",
                    retry_after=(stream.retry_at - timezone.now()).total_seconds(),
                )
            raise SSFOperationInProgress(
                "Another operation is running for this stream. Wait for it to finish and try again."
            )
        try:
            yield
        except SSFRemoteError as error:
            SSFProvisioning.record_error(stream, error)
            raise
        finally:
            SSFStream.objects.filter(organization=stream.organization, pk=stream.pk, operation_until=deadline).update(
                operation_until=None
            )

    @staticmethod
    def _store_configuration(connection: SSFConnection, stream: SSFStream, document: object) -> None:
        if not isinstance(document, dict) or document.get("iss") != connection.issuer:
            raise SSFRemoteError("The stream issuer does not match the trusted transmitter.")
        remote_id = document.get("stream_id")
        audiences = document.get("aud")
        if isinstance(audiences, str):
            audiences = [audiences]
        if not isinstance(remote_id, str) or not 1 <= len(remote_id) <= 255:
            raise SSFRemoteError("The transmitter returned an invalid stream ID.")
        if stream.remote_stream_id and remote_id != stream.remote_stream_id:
            raise SSFRemoteError("The transmitter returned a different stream ID.")
        if (
            not isinstance(audiences, list)
            or not 1 <= len(audiences) <= 20
            or not all(isinstance(audience, str) and 1 <= len(audience) <= 512 for audience in audiences)
        ):
            raise SSFRemoteError("The transmitter returned an invalid receiver audience.")
        if connection.audience and connection.audience not in audiences:
            raise SSFRemoteError("The assigned stream audience does not match the expected audience.")
        if stream.audiences and sorted(audiences) != sorted(stream.audiences):
            raise SSFRemoteError("The transmitter changed the immutable stream audience.")
        delivery = document.get("delivery")
        if (
            not isinstance(delivery, dict)
            or delivery.get("method") != PUSH_DELIVERY
            or delivery.get("endpoint_url") != stream.endpoint_url
        ):
            raise SSFRemoteError("The transmitter did not configure the requested push delivery endpoint.")
        delivered = document.get("events_delivered")
        if (
            not isinstance(delivered, list)
            or len(delivered) > 100
            or not all(isinstance(event, str) and event in stream.events_requested for event in delivered)
        ):
            raise SSFRemoteError("The transmitter returned invalid negotiated event types.")
        if (
            SSFStream.objects.filter(
                organization=stream.organization, connection=connection, remote_stream_id=remote_id
            )
            .exclude(pk=stream.pk)
            .exists()
        ):
            raise SSFRemoteError("This remote stream is already attached to this connection.")
        stream.remote_stream_id = remote_id
        stream.audiences = audiences
        stream.events_delivered = delivered
        stream.save(update_fields=["remote_stream_id", "audiences", "events_delivered"])

    @staticmethod
    def _read_status(connection: SSFConnection, stream: SSFStream) -> None:
        url = SSFProvisioning.endpoint(connection, "status_endpoint")
        document = SSFRemote.request(
            "GET", url, token=connection.remote_token, params={"stream_id": stream.remote_stream_id}
        )
        if (
            not isinstance(document, dict)
            or document.get("stream_id") != stream.remote_stream_id
            or document.get("status")
            not in (SSFStream.Status.ENABLED, SSFStream.Status.PAUSED, SSFStream.Status.DISABLED)
        ):
            raise SSFRemoteError("The transmitter returned an invalid stream status.")
        stream.status = document["status"]
        reason = document.get("reason", "")
        stream.reason = reason[:1024] if isinstance(reason, str) else ""

    @staticmethod
    @sensitive_variables("token", "payload", "document", "candidate")
    def provision(
        config: SSFConfiguration,
        stream: SSFStream,
        *,
        description: str | None = None,
        events_requested: list[str] | None = None,
    ) -> SSFStream:
        connection = SSFProvisioning._require_incoming(config, stream)
        if not SSFService.is_connection_enabled(config, connection):
            raise ValueError("Enable SSF and this connection before provisioning incoming streams.")
        if not connection.remote_token:
            raise ValueError("Set the transmitter API bearer token on this connection before provisioning streams.")
        with SSFProvisioning.operation(stream):
            if description is not None:
                stream.description = description
            if events_requested is not None:
                stream.events_requested = events_requested
            recover = bool(stream.receiver_token_hash)
            token = stream.receiver_token or f"phssf_{secrets.token_urlsafe(32)}"
            stream.receiver_token = token
            stream.status = SSFStream.Status.PROVISIONING
            stream.endpoint_url = f"{SSFService.issuer(config.organization)}/events/{stream.id}"
            stream.receiver_token_hash = SSFService.token_hash(token)
            stream.last_error = ""
            stream.retry_at = None
            stream.save(
                update_fields=[
                    "status",
                    "endpoint_url",
                    "receiver_token_hash",
                    "receiver_token",
                    "description",
                    "events_requested",
                    "last_error",
                    "retry_at",
                ]
            )
            try:
                SSFProvisioning.refresh_connection(connection)
                connection.save(update_fields=["metadata", "jwks_uri", "legacy_jwks", "discovered_at", "updated_at"])
                methods = connection.metadata.get("delivery_methods_supported", [])
                if methods and PUSH_DELIVERY not in methods:
                    raise SSFRemoteError(
                        "The transmitter does not support push delivery. Incoming SSF streams currently require push delivery."
                    )
                url = SSFProvisioning.endpoint(connection, "configuration_endpoint")
                marker = f"PostHog stream {stream.id}"
                payload: dict[str, JsonValue] = {
                    "events_requested": stream.events_requested,
                    "description": f"{marker}: {stream.description}"[:1024],
                    "delivery": {
                        "method": PUSH_DELIVERY,
                        "endpoint_url": stream.endpoint_url,
                        "authorization_header": f"Bearer {token}",
                    },
                }
                if not stream.remote_stream_id and recover:
                    candidates = SSFRemote.request("GET", url, token=connection.remote_token)
                    if not isinstance(candidates, list):
                        raise SSFRemoteError(
                            "The transmitter must list stream configurations before a failed setup can be retried safely."
                        )
                    matching = [
                        candidate
                        for candidate in candidates
                        if isinstance(candidate, dict)
                        and isinstance(candidate.get("description"), str)
                        and candidate["description"].startswith(f"{marker}:")
                    ]
                    if len(matching) > 1:
                        raise SSFRemoteError(
                            "Multiple remote streams match this setup. Remove the duplicate streams at the transmitter before retrying."
                        )
                    if matching:
                        # A lost create response must not create a second upstream stream on retry.
                        stream.remote_stream_id = matching[0].get("stream_id", "")
                        if not isinstance(stream.remote_stream_id, str) or not 1 <= len(stream.remote_stream_id) <= 255:
                            raise SSFRemoteError("The transmitter returned an invalid stream ID during recovery.")
                if stream.remote_stream_id:
                    payload["stream_id"] = stream.remote_stream_id
                document = SSFRemote.request(
                    "PATCH" if stream.remote_stream_id else "POST", url, token=connection.remote_token, body=payload
                )
                SSFProvisioning._store_configuration(connection, stream, document)
                stream.status = SSFStream.Status.ENABLED
                if connection.metadata.get("status_endpoint"):
                    SSFProvisioning._read_status(connection, stream)
                stream.save(update_fields=["status", "reason"])
            except SSFRemoteError as error:
                stream.status = SSFStream.Status.FAILED
                stream.save(update_fields=["status"])
                SSFProvisioning.record_error(stream, error)
                report_organization_action(config.organization, "ssf stream provisioning failed")
                return stream
        report_organization_action(config.organization, "ssf stream provisioned", {"direction": "incoming"})
        if connection.metadata.get("verification_endpoint"):
            try:
                SSFProvisioning.verify(config, stream)
            except SSFRemoteError as error:
                SSFProvisioning.record_error(stream, error)
        return stream

    @staticmethod
    @sensitive_variables("state", "nonce")
    def verify(config: SSFConfiguration, stream: SSFStream, state: str | None = None) -> None:
        connection = SSFProvisioning._require_incoming(config, stream)
        if not stream.remote_stream_id or stream.status in (SSFStream.Status.PROVISIONING, SSFStream.Status.FAILED):
            raise ValueError("Finish provisioning the stream before requesting verification.")
        with SSFProvisioning.operation(stream):
            nonce = (
                state
                if state is not None
                else (stream.verification_state if stream.last_verified_at is None else None)
                or secrets.token_urlsafe(32)
            )
            stream.verification_state = nonce
            stream.last_verified_at = None
            stream.verification_requested_at = timezone.now()
            stream.last_error = ""
            stream.save(
                update_fields=["verification_state", "verification_requested_at", "last_verified_at", "last_error"]
            )
            SSFRemote.request(
                "POST",
                SSFProvisioning.endpoint(connection, "verification_endpoint"),
                token=connection.remote_token,
                body={"stream_id": stream.remote_stream_id, "state": nonce},
            )
        report_organization_action(config.organization, "ssf verification requested")

    @staticmethod
    def set_status(config: SSFConfiguration, stream: SSFStream, status: str, reason: str = "") -> SSFStream:
        connection = SSFProvisioning._require_incoming(config, stream)
        with SSFProvisioning.operation(stream):
            SSFRemote.request(
                "POST",
                SSFProvisioning.endpoint(connection, "status_endpoint"),
                token=connection.remote_token,
                body={"stream_id": stream.remote_stream_id, "status": status, "reason": reason},
            )
            SSFProvisioning._read_status(connection, stream)
            stream.save(update_fields=["status", "reason"])
        return stream

    @staticmethod
    @sensitive_variables("subject")
    def subject(config: SSFConfiguration, stream: SSFStream, subject: dict[str, JsonValue], *, remove: bool) -> None:
        connection = SSFProvisioning._require_incoming(config, stream)
        endpoint = "remove_subject_endpoint" if remove else "add_subject_endpoint"
        with SSFProvisioning.operation(stream):
            SSFRemote.request(
                "POST",
                SSFProvisioning.endpoint(connection, endpoint),
                token=connection.remote_token,
                body={"stream_id": stream.remote_stream_id, "subject": subject},
            )

    @staticmethod
    def delete_stream(config: SSFConfiguration, stream: SSFStream) -> None:
        if (
            stream.connection
            and stream.connection.direction == SSFConnection.Direction.INCOMING
            and stream.remote_stream_id
            and stream.connection.remote_token
        ):
            with SSFProvisioning.operation(stream):
                SSFRemote.request(
                    "DELETE",
                    SSFProvisioning.endpoint(stream.connection, "configuration_endpoint"),
                    token=stream.connection.remote_token,
                    params={"stream_id": stream.remote_stream_id},
                )
        SSFEvent.objects.filter(
            organization=config.organization, stream=stream, direction=SSFEvent.Direction.OUTGOING
        ).delete()
        stream.delete()
        report_organization_action(config.organization, "ssf stream deleted")
