"""
This module contains serializers that are used across other serializers for nested representations.
"""

from typing import Optional

from rest_framework import serializers

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership


class UserBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "uuid",
            "distinct_id",
            "first_name",
            "last_name",
            "email",
            "is_email_verified",
        ]


class TeamBasicSerializer(serializers.ModelSerializer):
    """
    Serializer for `Team` model with minimal attributes to speeed up loading and transfer times.
    Also used for nested serializers.
    """

    class Meta:
        model = Team
        fields = (
            "id",
            "uuid",
            "organization",
            "api_token",
            "name",
            "completed_snippet_onboarding",
            "has_completed_onboarding_for",
            "ingested_event",
            "is_demo",
            "timezone",
            "access_control",
        )
        read_only_fields = fields


class TeamPublicSerializer(serializers.ModelSerializer):
    """
    Serializer for `Team` model with attributes suitable for completely public sharing (primarily shared dashboards).
    """

    class Meta:
        model = Team
        fields = (
            "id",
            "uuid",
            "name",
            "timezone",
        )
        read_only_fields = fields


class OrganizationBasicSerializer(serializers.ModelSerializer):
    """
    Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
    Also used for nested serializers.
    """

    membership_level = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ["id", "name", "slug", "membership_level"]

    def get_membership_level(self, organization: Organization) -> Optional[OrganizationMembership.Level]:
        membership = OrganizationMembership.objects.filter(
            organization=organization, user=self.context["request"].user
        ).first()
        return membership.level if membership is not None else None
