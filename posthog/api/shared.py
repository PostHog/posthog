"""
This module contains serializers that are used across other serializers for nested representations.
"""

from rest_framework import serializers

from posthog.models import Organization, Team, User


class UserBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "uuid", "distinct_id", "first_name", "email"]


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
            "ingested_event",
            "is_demo",
            "timezone",
        )


class OrganizationBasicSerializer(serializers.ModelSerializer):
    """
    Serializer for `Organization` model with minimal attributes to speeed up loading and transfer times.
    Also used for nested serializers.
    """

    class Meta:
        model = Organization
        fields = [
            "id",
            "name",
        ]
