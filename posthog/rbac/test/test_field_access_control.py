import pytest
from posthog.test.base import BaseTest

from django.db import models

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from posthog.models.team import Team
from posthog.rbac.decorators import field_access_control
from posthog.rbac.user_access_control import (
    UserAccessControl,
    UserAccessControlSerializerMixin,
    get_field_access_control_map,
)


class TestFieldAccessControlDecorator(BaseTest):
    def test_decorator_adds_metadata_to_field(self):
        """Test that the decorator adds access control metadata to fields"""
        field = Team._meta.get_field("session_recording_opt_in")

        assert hasattr(field, "_access_control_resource")
        assert hasattr(field, "_access_control_level")
        assert field._access_control_resource == "project"
        assert field._access_control_level == "admin"

    def test_get_field_access_control_map_returns_decorated_fields(self):
        """Test that get_field_access_control_map correctly finds decorated fields"""
        field_map = get_field_access_control_map(Team)

        expected_fields = [
            "session_recording_opt_in",
            "session_recording_sample_rate",
            "session_recording_minimum_duration_milliseconds",
            "session_recording_linked_flag",
            "session_recording_network_payload_capture_config",
            "session_recording_masking_config",
            "session_recording_url_trigger_config",
            "session_recording_url_blocklist_config",
            "session_recording_event_trigger_config",
            "session_recording_trigger_match_type_config",
            "session_replay_config",
        ]

        for field_name in expected_fields:
            assert field_name in field_map
            assert field_map[field_name] == ("project", "admin")

    def test_serializer_validation_with_decorator(self):
        """Test that serializer validation blocks a non-admin from editing a project-admin-guarded field"""
        team = Team.objects.create(
            organization=self.organization,
            api_token="token123abc",
        )

        class TeamSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
            class Meta:
                model = Team
                fields = ["session_recording_opt_in", "session_recording_sample_rate"]

        user_no_access = self._create_user("no_access@test.com")
        self.organization_membership.save()

        user_access_control = UserAccessControl(user_no_access, team)

        # Simulate a non-admin: object-level check returns False
        user_access_control.check_access_level_for_object = lambda obj, level: False  # type: ignore

        serializer = TeamSerializer(
            instance=team, data={"session_recording_opt_in": True}, context={"user_access_control": user_access_control}
        )

        with pytest.raises(ValidationError) as exc_info:
            serializer.is_valid(raise_exception=True)

        detail = exc_info.value.detail
        assert isinstance(detail, dict), f"Expected dict but got {type(detail)}"
        assert "session_recording_opt_in" in detail
        error_detail = detail["session_recording_opt_in"]
        error_msg = error_detail[0] if isinstance(error_detail, list) else str(error_detail)
        assert "You need admin access to projects" in str(error_msg)

    def test_field_access_control_helper(self):
        """Test the field_access_control helper function"""

        class TestModel(models.Model):
            test_field = field_access_control(models.CharField(max_length=100), "notebook", "viewer")

            class Meta:
                app_label = "test"

        # Get field access control map
        field_map = get_field_access_control_map(TestModel)

        assert "test_field" in field_map
        assert field_map["test_field"] == ("notebook", "viewer")

        # Also check that the field has the metadata directly
        field = TestModel._meta.get_field("test_field")
        assert hasattr(field, "_access_control_resource")
        assert hasattr(field, "_access_control_level")
        assert field._access_control_resource == "notebook"
        assert field._access_control_level == "viewer"

    def test_project_resource_uses_object_level_check(self):
        """
        field_access_control with resource="project" must check the user's actual
        project-level (object-level) access, not the resource default which is always "admin".
        A regular project member must be blocked from editing an "admin"-guarded field
        even though access_level_for_resource("project") always returns "admin".
        """
        team = Team.objects.create(
            organization=self.organization,
            api_token="token456def",
        )

        # session_recording_opt_in is decorated with ("project", "admin") on the Team model
        class TeamSerializer(UserAccessControlSerializerMixin, serializers.ModelSerializer):
            class Meta:
                model = Team
                fields = ["session_recording_opt_in"]

        user_member = self._create_user("member@test.com")
        user_access_control = UserAccessControl(user_member, team)

        # Simulate a non-admin project member: object-level check returns False.
        # resource-level check would incorrectly return True (the bug), so we confirm
        # the fix routes through the object-level check for "project" resources.
        user_access_control.check_access_level_for_object = lambda obj, level: False  # type: ignore
        user_access_control.check_access_level_for_resource = lambda resource, level: True  # type: ignore

        serializer = TeamSerializer(
            instance=team,
            data={"session_recording_opt_in": True},
            context={"user_access_control": user_access_control},
        )

        with pytest.raises(ValidationError) as exc_info:
            serializer.is_valid(raise_exception=True)

        detail = exc_info.value.detail
        assert "session_recording_opt_in" in detail
