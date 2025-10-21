import uuid

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock

from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, status
from rest_framework.response import Response

from posthog.api.mixins import validated_request


class EventCaptureRequestSerializer(serializers.Serializer):
    event = serializers.CharField(max_length=200, help_text="Event name")
    distinct_id = serializers.CharField(max_length=200, help_text="User distinct ID")
    properties = serializers.DictField(required=False, default=dict, help_text="Event properties")
    timestamp = serializers.DateTimeField(required=False, allow_null=True)


class EventCaptureResponseSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=["ok", "queued"])
    event_id = serializers.UUIDField()
    distinct_id = serializers.CharField()


class ErrorResponseSerializer(serializers.Serializer):
    type = serializers.CharField()
    code = serializers.CharField()
    detail = serializers.CharField()


class TestValidatedRequestDecorator(APIBaseTest):
    def test_request_validation_with_valid_event_data(self):
        """All valid data, should return 200 OK"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def capture_event(view_self, request):
            distinct_id = request.validated_data["distinct_id"]
            return Response(
                {
                    "status": "ok",
                    "event_id": str(uuid.uuid4()),
                    "distinct_id": distinct_id,
                },
                status=status.HTTP_200_OK,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})

        mock_request = Mock()
        mock_request.data = {
            "event": "$pageview",
            "distinct_id": "user_123",
            "properties": {"$current_url": "https://posthog.com"},
        }

        response = capture_event(view_instance, mock_request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"
        assert response.data["distinct_id"] == "user_123"
        assert mock_request.validated_data["event"] == "$pageview"

    def test_request_validation_with_missing_required_field(self):
        """Missing required field, should raise validation error"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def capture_event(view_self, request):
            return Response({"status": "ok", "event_id": str(uuid.uuid4())}, status=status.HTTP_200_OK)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {"event": "$pageview"}  # Missing 'distinct_id'

        with pytest.raises(Exception) as exc_info:
            capture_event(view_instance, mock_request)

        assert "distinct_id" in str(exc_info.value)

    def test_error_response_validation(self):
        """Error response, should return validated 400 BAD REQUEST"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
                400: OpenApiResponse(response=ErrorResponseSerializer),
            },
        )
        def capture_event(view_self, request):
            return Response(
                {"type": "validation_error", "code": "invalid_event", "detail": "Event name is invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        response = capture_event(view_instance, mock_request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["type"] == "validation_error"
        assert response.data["code"] == "invalid_event"

    def test_undeclared_status_code_raises_error(self):
        """Undeclared status code, should raise ValueError"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def capture_event(view_self, request):
            return Response(
                {"type": "server_error", "code": "internal", "detail": "Server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        with pytest.raises(ValueError) as exc_info:
            capture_event(view_instance, mock_request)

        assert "Response status code 500 not declared" in str(exc_info.value)
        assert "Declared status codes: [200]" in str(exc_info.value)

    def test_invalid_response_data_raises_error(self):
        """Invalid response data, should raise validation error"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def capture_event(view_self, request):
            # Missing required fields in response
            return Response({"wrong_field": "value"}, status=status.HTTP_200_OK)

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        with pytest.raises(Exception):
            capture_event(view_instance, mock_request)

    def test_no_response_serializers_bypasses_validation(self):
        """No response serializers, should bypass validation"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
        )
        def capture_event(view_self, request):
            # Can return anything when no response serializers, helps smooth adoption
            return Response({"custom_response": "anything goes"}, status=status.HTTP_200_OK)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        response = capture_event(view_instance, mock_request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["custom_response"] == "anything goes"
