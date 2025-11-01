import uuid

import pytest
from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

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
        def mock_endpoint(view_self, request):
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

        response = mock_endpoint(view_instance, mock_request)

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
        def mock_endpoint(view_self, request):
            return Response({"status": "ok", "event_id": str(uuid.uuid4())}, status=status.HTTP_200_OK)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {"event": "$pageview"}  # Missing 'distinct_id'

        with pytest.raises(Exception) as exc_info:
            mock_endpoint(view_instance, mock_request)

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
        def mock_endpoint(view_self, request):
            return Response(
                {"type": "validation_error", "code": "invalid_event", "detail": "Event name is invalid"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        response = mock_endpoint(view_instance, mock_request)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["type"] == "validation_error"
        assert response.data["code"] == "invalid_event"

    def test_undeclared_status_code_logs_warning(self):
        """Undeclared status code, should log warning and return response"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def mock_endpoint(view_self, request):
            return Response(
                {"type": "server_error", "code": "internal", "detail": "Server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Should log a warning and return the response
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = True
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                # Verify the warning was logged
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert (
                    "Response status code not declared in responses parameter of the @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date"
                    in call_args[0][0]
                )
                assert call_args[1]["view_func"] == "mock_endpoint"
                assert call_args[1]["status_code"] == 500
                assert call_args[1]["declared_status_codes"] == [200]

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.data["type"] == "server_error"

    def test_invalid_response_data_logs_warning(self):
        """Invalid response data, should log warning and return response"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def mock_endpoint(view_self, request):
            # Missing required fields in response
            return Response({"wrong_field": "value"}, status=status.HTTP_200_OK)

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Should log a warning and return the response
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = True
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                # Verify the warning was logged
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert (
                    "Response data does not match declared serializer for status code 200 declared in responses parameter of the @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date"
                    in call_args[0][0]
                )
                assert call_args[1]["view_func"] == "mock_endpoint"
                assert call_args[1]["status_code"] == 200
                assert call_args[1]["serializer_class"] == "EventCaptureResponseSerializer"
                assert "validation_errors" in call_args[1]

        assert response.status_code == status.HTTP_200_OK
        assert response.data["wrong_field"] == "value"

    def test_no_response_serializers_bypasses_validation(self):
        """No response serializers, should bypass validation"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
        )
        def mock_endpoint(view_self, request):
            # Can return anything when no response serializers, helps smooth adoption
            return Response({"custom_response": "anything goes"}, status=status.HTTP_200_OK)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        response = mock_endpoint(view_instance, mock_request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["custom_response"] == "anything goes"

    def test_non_response_object_logs_warning(self):
        """Non-Response object return, should log warning and return result"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def mock_endpoint(view_self, request):
            # Return a dict instead of Response object
            return {"status": "ok", "event_id": "test-event-id"}

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Should log a warning and return the result
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = True
            with patch("posthog.api.mixins.logger") as mock_logger:
                result = mock_endpoint(view_instance, mock_request)

                # Verify the warning was logged
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert (
                    "View must return a Response object when using @validated_request with response serializers. Please update the provided API schema to ensure API docs remain up to date"
                    in call_args[0][0]
                )
                assert call_args[1]["view_func"] == "mock_endpoint"
                assert call_args[1]["result_type"] == "dict"

        # Should return the original result
        assert result == {"status": "ok", "event_id": "test-event-id"}

    def test_warnings_only_in_debug_mode(self):
        """Warnings should only be logged when DEBUG=True"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
        )
        def mock_endpoint(view_self, request):
            return Response(
                {"type": "server_error", "code": "internal", "detail": "Server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Test with DEBUG=False (production mode)
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = False
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                # Should not log any warnings in production
                mock_logger.warning.assert_not_called()

        # Test with DEBUG=True (development mode)
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = True
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                # Should log warning in development
                mock_logger.warning.assert_called_once()

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

    def test_strict_response_validation_undeclared_status_code_raises(self):
        """Strict response validation: undeclared status code should raise exception"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
            strict_response_validation=True,
        )
        def mock_endpoint(view_self, request):
            return Response(
                {"type": "server_error", "code": "internal", "detail": "Server error"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Should raise ValidationError regardless of DEBUG setting
        with pytest.raises(serializers.ValidationError) as exc_info:
            mock_endpoint(view_instance, mock_request)

        assert "Response status code 500 not declared" in str(exc_info.value)
        assert "Declared status codes" in str(exc_info.value)

    def test_strict_response_validation_invalid_data_raises(self):
        """Strict response validation: invalid response data should raise exception"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
            strict_response_validation=True,
        )
        def mock_endpoint(view_self, request):
            # Missing required fields in response
            return Response({"wrong_field": "value"}, status=status.HTTP_200_OK)

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Should raise ValidationError with serializer errors
        with pytest.raises(serializers.ValidationError) as exc_info:
            mock_endpoint(view_instance, mock_request)

        # The error should contain field validation errors
        error_detail = exc_info.value.detail
        assert "status" in str(error_detail) or "event_id" in str(error_detail) or "distinct_id" in str(error_detail)

    def test_strict_response_validation_valid_data_succeeds(self):
        """Strict response validation: valid response data should succeed"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
            strict_response_validation=True,
        )
        def mock_endpoint(view_self, request):
            return Response(
                {
                    "status": "ok",
                    "event_id": str(uuid.uuid4()),
                    "distinct_id": request.validated_data["distinct_id"],
                },
                status=status.HTTP_200_OK,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview", "distinct_id": "user_123"}

        # Should work normally with valid data
        response = mock_endpoint(view_instance, mock_request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"
        assert response.data["distinct_id"] == "user_123"

    def test_non_strict_request_validation_logs_warning(self):
        """Non-strict request validation: invalid data should log warning and continue"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
            strict_request_validation=False,
        )
        def mock_endpoint(view_self, request):
            # Endpoint continues processing despite validation failure
            return Response(
                {
                    "status": "ok",
                    "event_id": str(uuid.uuid4()),
                    "distinct_id": "test_user",
                },
                status=status.HTTP_200_OK,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview"}  # Missing required 'distinct_id'

        # Should log a warning but not raise
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = True
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                # Verify the warning was logged
                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert (
                    "Request data does not match declared serializer in @validated_request decorator. Please update the provided API schema to ensure API docs remain up to date"
                    in call_args[0][0]
                )
                assert call_args[1]["view_func"] == "mock_endpoint"
                assert call_args[1]["serializer_class"] == "EventCaptureRequestSerializer"
                assert "validation_errors" in call_args[1]

        # Should not raise and should continue processing
        assert response.status_code == status.HTTP_200_OK

    def test_non_strict_request_validation_no_warning_when_debug_false(self):
        """Non-strict request validation: should not log warning when DEBUG=False"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
            strict_request_validation=False,
        )
        def mock_endpoint(view_self, request):
            return Response(
                {
                    "status": "ok",
                    "event_id": str(uuid.uuid4()),
                    "distinct_id": request.validated_data.get("distinct_id", "unknown"),
                },
                status=status.HTTP_200_OK,
            )

        view_instance = Mock()
        view_instance.get_serializer_context = Mock(return_value={})
        mock_request = Mock()
        mock_request.data = {"event": "$pageview"}  # Missing required 'distinct_id'

        # Should not log warning when DEBUG=False
        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = False
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                # Should not log any warnings in production
                mock_logger.warning.assert_not_called()

        # Should still proceed without raising
        assert response.status_code == status.HTTP_200_OK

    def test_non_strict_request_validation_valid_data_succeeds(self):
        """Non-strict request validation: valid data should work normally"""

        @validated_request(
            request_serializer=EventCaptureRequestSerializer,
            responses={
                200: OpenApiResponse(response=EventCaptureResponseSerializer),
            },
            strict_request_validation=False,
        )
        def mock_endpoint(view_self, request):
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

        # Should work normally with valid data
        response = mock_endpoint(view_instance, mock_request)

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "ok"
        assert response.data["distinct_id"] == "user_123"
        assert mock_request.validated_data["event"] == "$pageview"

    def test_no_body_response_declared_as_none_succeeds(self):
        """When status code is declared as None (no body), response with no body should succeed"""

        @validated_request(
            responses={
                204: None,
            },
        )
        def mock_endpoint(view_self, request):
            return Response(status=status.HTTP_204_NO_CONTENT)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {}

        response = mock_endpoint(view_instance, mock_request)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.data is None

    def test_no_body_response_with_body_warns(self):
        """When status code is declared as None but response has body, should warn"""

        @validated_request(
            responses={
                204: None,
            },
        )
        def mock_endpoint(view_self, request):
            return Response({"error": "should not have body"}, status=status.HTTP_204_NO_CONTENT)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {}

        with patch("posthog.api.mixins.settings") as mock_settings:
            mock_settings.DEBUG = True
            with patch("posthog.api.mixins.logger") as mock_logger:
                response = mock_endpoint(view_instance, mock_request)

                mock_logger.warning.assert_called_once()
                call_args = mock_logger.warning.call_args
                assert (
                    "Response status code 204 is declared with no body, but response contains data. Please update the provided API schema to ensure API docs remain up to date"
                    in call_args[0][0]
                )
                assert call_args[1]["status_code"] == 204

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_no_body_response_with_body_strict_raises(self):
        """When status code is declared as None but response has body with strict validation, should raise"""

        @validated_request(
            responses={
                204: None,
            },
            strict_response_validation=True,
        )
        def mock_endpoint(view_self, request):
            return Response({"error": "should not have body"}, status=status.HTTP_204_NO_CONTENT)

        view_instance = Mock()
        mock_request = Mock()
        mock_request.data = {}

        with pytest.raises(serializers.ValidationError) as exc_info:
            mock_endpoint(view_instance, mock_request)

        assert "Response status code 204 is declared with no body, but response contains data" in str(exc_info.value)
