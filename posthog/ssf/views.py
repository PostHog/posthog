from typing import Any

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils.crypto import constant_time_compare
from django.views.decorators.debug import sensitive_variables

from drf_spectacular.utils import extend_schema
from rest_framework import exceptions
from rest_framework.parsers import BaseParser, JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from posthog.event_usage import report_organization_action
from posthog.models.ssf import SSFConfiguration, SSFConnection, SSFStream
from posthog.ssf.provisioning import SSFProvisioning
from posthog.ssf.remote import SSFRemoteError
from posthog.ssf.serializers import (
    PollRequestSerializer,
    StreamIDSerializer,
    StreamRequestSerializer,
    StreamStatusSerializer,
    SubjectRequestSerializer,
    VerificationRequestSerializer,
)
from posthog.ssf.service import SETValidationError, SSFService
from posthog.ssf.validation import CONTROL_EVENTS, MAX_TOKEN_BYTES, POLL_DELIVERY


class SSFNotReady(exceptions.APIException):
    status_code = 503
    default_detail = "The SSF stream is being provisioned. Retry delivery shortly."
    default_code = "ssf_not_ready"


class SSFThrottle(SimpleRateThrottle):
    rate = "120/minute"
    scope = "ssf"

    def get_cache_key(self, request: Request, view: APIView) -> str:
        return f"ssf:{view.kwargs['organization_id']}:{self.get_ident(request)}"


@extend_schema(exclude=True)
class SSFBaseView(APIView):
    authentication_classes: list = []
    permission_classes: list = []
    renderer_classes = [JSONRenderer]
    parser_classes = [JSONParser]
    throttle_classes = [SSFThrottle]
    role = "transmitter"
    config: SSFConfiguration

    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        self.config = get_object_or_404(
            SSFConfiguration.objects.select_related("organization"),
            organization_id=kwargs["organization_id"],
            enabled=True,
        )
        if not SSFService.is_enabled(self.config):
            raise Http404

    def finalize_response(self, request: Request, response: Response, *args: Any, **kwargs: Any) -> Response:
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class SSFDiscoveryView(SSFBaseView):
    def get(self, request: Request, **kwargs: Any) -> Response:
        issuer = SSFService.issuer(self.config.organization)
        return Response(
            {
                "spec_version": "1_0",
                "issuer": issuer,
                "jwks_uri": f"{issuer}/jwks.json",
                "delivery_methods_supported": [POLL_DELIVERY],
                "configuration_endpoint": f"{issuer}/stream",
                "status_endpoint": f"{issuer}/status",
                "add_subject_endpoint": f"{issuer}/subjects:add",
                "remove_subject_endpoint": f"{issuer}/subjects:remove",
                "verification_endpoint": f"{issuer}/verify",
                "authorization_schemes": [{"spec_urn": "urn:ietf:rfc:6750"}],
                "default_subjects": "NONE",
            }
        )


class SSFJWKSView(SSFBaseView):
    def get(self, request: Request, **kwargs: Any) -> Response:
        return Response({"keys": SSFService.public_keys(self.config)})


class SSFAuthenticatedView(SSFBaseView):
    connection: SSFConnection
    receiver_stream: SSFStream

    @sensitive_variables("authorization", "credential", "expected")
    def initial(self, request: Request, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        authorization = request.headers.get("Authorization", "").split()
        if len(authorization) != 2 or authorization[0].lower() != "bearer":
            raise exceptions.AuthenticationFailed("Provide a valid SSF bearer credential.")
        credential = SSFService.token_hash(authorization[1])
        if self.role == "receiver":
            streams = SSFStream.objects.select_related("connection").filter(
                organization=self.config.organization,
                connection__organization=self.config.organization,
                connection__enabled=True,
                connection__direction=SSFConnection.Direction.INCOMING,
            )
            if "stream_id" in kwargs:
                stream = get_object_or_404(streams, pk=kwargs["stream_id"])
            else:
                found = streams.filter(receiver_token_hash=credential).first()
                if found is None:
                    raise exceptions.AuthenticationFailed("Provide a valid SSF delivery credential.")
                stream = found
            if not stream.receiver_token_hash or not constant_time_compare(stream.receiver_token_hash, credential):
                raise exceptions.AuthenticationFailed("Provide a valid SSF delivery credential.")
            if stream.status == SSFStream.Status.PROVISIONING or not stream.audiences:
                raise SSFNotReady()
            self.receiver_stream = stream
            assert stream.connection is not None
            self.connection = stream.connection
        else:
            connection = SSFConnection.objects.filter(
                organization=self.config.organization,
                enabled=True,
                direction=SSFConnection.Direction.OUTGOING,
                token_hash=credential,
            ).first()
            if connection is None:
                raise exceptions.AuthenticationFailed("Provide a valid SSF management credential.")
            self.connection = connection

    def get_authenticate_header(self, request: Request) -> str:
        return 'Bearer realm="ssf"'

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, SSFStream.DoesNotExist):
            exc = exceptions.NotFound("The stream is no longer available.")
        return super().handle_exception(exc)

    def stream(self, value: object, *, lock: bool = False) -> SSFStream:
        serializer = StreamIDSerializer(data={"stream_id": value})
        serializer.is_valid(raise_exception=True)
        queryset = SSFStream.objects.filter(organization=self.config.organization, connection=self.connection)
        if lock:
            queryset = queryset.select_for_update()
        return get_object_or_404(queryset, pk=serializer.validated_data["stream_id"])


class SSFStreamView(SSFAuthenticatedView):
    def get(self, request: Request, **kwargs: Any) -> Response:
        stream_id = request.query_params.get("stream_id")
        if stream_id is not None:
            return Response(SSFService.stream_configuration(self.config, self.stream(stream_id)))
        streams = SSFStream.objects.filter(organization=self.config.organization, connection=self.connection).order_by(
            "created_at", "id"
        )
        return Response([SSFService.stream_configuration(self.config, stream) for stream in streams])

    def post(self, request: Request, **kwargs: Any) -> Response:
        serializer = StreamRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            stream = SSFService.create_outgoing_stream(
                self.config,
                self.connection,
                serializer.validated_data.get("events_requested", CONTROL_EVENTS),
                serializer.validated_data.get("description", ""),
            )
        except ValueError as error:
            raise exceptions.ValidationError(str(error)) from error
        return Response(SSFService.stream_configuration(self.config, stream), status=201)

    def _update(self, request: Request, *, replace: bool) -> Response:
        serializer = StreamRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if "stream_id" not in serializer.validated_data:
            raise exceptions.ValidationError({"stream_id": "Provide the stream ID."})
        with transaction.atomic():
            stream = self.stream(serializer.validated_data["stream_id"], lock=True)
            current = SSFService.stream_configuration(self.config, stream)
            for field in (
                "iss",
                "aud",
                "events_supported",
                "events_delivered",
                "min_verification_interval",
                "inactivity_timeout",
            ):
                if field in request.data and request.data[field] != current.get(field):
                    raise exceptions.ValidationError(
                        {field: "This transmitter-supplied value does not match the stream."}
                    )
            delivery = serializer.validated_data.get("delivery", {})
            expected_endpoint = f"{SSFService.issuer(self.config.organization)}/poll/{stream.id}"
            if "endpoint_url" in delivery and delivery["endpoint_url"] != expected_endpoint:
                raise exceptions.ValidationError({"delivery": "The polling endpoint cannot be changed."})
            for field, default in (("events_requested", []), ("description", "")):
                if field in serializer.validated_data or replace:
                    setattr(stream, field, serializer.validated_data.get(field, default))
            supported = [*CONTROL_EVENTS, *self.config.event_types]
            stream.events_delivered = [event for event in stream.events_requested if event in supported]
            stream.save(update_fields=["events_requested", "events_delivered", "description"])
        report_organization_action(self.config.organization, "ssf stream updated")
        return Response(SSFService.stream_configuration(self.config, stream))

    def patch(self, request: Request, **kwargs: Any) -> Response:
        return self._update(request, replace=False)

    def put(self, request: Request, **kwargs: Any) -> Response:
        return self._update(request, replace=True)

    def delete(self, request: Request, **kwargs: Any) -> Response:
        SSFProvisioning.delete_stream(self.config, self.stream(request.query_params.get("stream_id")))
        return Response(status=204)


class SSFStatusView(SSFAuthenticatedView):
    def get(self, request: Request, **kwargs: Any) -> Response:
        stream = self.stream(request.query_params.get("stream_id"))
        return Response({"stream_id": str(stream.id), "status": stream.status, "reason": stream.reason})

    def post(self, request: Request, **kwargs: Any) -> Response:
        serializer = StreamStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stream = SSFService.set_status_from_receiver(
            self.config,
            self.stream(serializer.validated_data["stream_id"]),
            serializer.validated_data["status"],
            serializer.validated_data["reason"],
        )
        report_organization_action(self.config.organization, "ssf stream status changed", {"status": stream.status})
        return Response({"stream_id": str(stream.id), "status": stream.status, "reason": stream.reason})


class SSFSubjectView(SSFAuthenticatedView):
    remove = False

    def post(self, request: Request, **kwargs: Any) -> Response:
        serializer = SubjectRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stream = self.stream(serializer.validated_data["stream_id"])
        try:
            SSFService.update_subject(self.config, stream, serializer.validated_data["subject"], remove=self.remove)
        except ValueError as error:
            raise exceptions.ValidationError(str(error)) from error
        return Response(status=204 if self.remove else 200)


class SSFVerificationView(SSFAuthenticatedView):
    def post(self, request: Request, **kwargs: Any) -> Response:
        serializer = VerificationRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        stream = self.stream(serializer.validated_data["stream_id"])
        try:
            SSFService.request_verification(self.config, stream, serializer.validated_data.get("state"))
        except ValueError as error:
            raise exceptions.ValidationError(str(error)) from error
        return Response(status=204)


class SSFPollView(SSFAuthenticatedView):
    def post(self, request: Request, **kwargs: Any) -> Response:
        serializer = PollRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            SSFService.poll_stream(
                self.config,
                self.stream(kwargs["stream_id"]),
                max_events=data["maxEvents"],
                return_immediately=data["returnImmediately"],
                acknowledged=[*data["ack"], *data["setErrs"]],
            )
        )


class SecurityEventParser(BaseParser):
    media_type = "application/secevent+jwt"

    def parse(self, stream: Any, media_type: str | None = None, parser_context: Any = None) -> dict[str, str]:
        raw = stream.read(MAX_TOKEN_BYTES + 1)
        if len(raw) > MAX_TOKEN_BYTES:
            raise exceptions.ParseError("The security event token exceeds the 64 KiB limit.")
        try:
            return {"token": raw.decode("ascii")}
        except UnicodeDecodeError as error:
            raise exceptions.ParseError("The request must contain an ASCII-encoded security event token.") from error


class SSFReceiverView(SSFAuthenticatedView):
    role = "receiver"
    parser_classes = [SecurityEventParser]

    @sensitive_variables("token")
    def post(self, request: Request, **kwargs: Any) -> Response:
        try:
            token = request.data.get("token", "")
            SSFService.consume_event(self.config, self.receiver_stream, token)
        except SETValidationError as error:
            report_organization_action(self.config.organization, "ssf event rejected", {"error_code": error.code})
            return Response(
                {"err": error.code, "description": str(error)}, status=400, headers={"Content-Language": "en"}
            )
        except SSFRemoteError as error:
            return Response(
                {"detail": str(error)}, status=503, headers={"Retry-After": str(int(error.retry_after or 60))}
            )
        except exceptions.ParseError as error:
            return Response(
                {"err": "invalid_request", "description": str(error)}, status=400, headers={"Content-Language": "en"}
            )
        return Response(status=202)
