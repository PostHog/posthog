from rest_framework import serializers

from posthog.models import User


class UserBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "distinct_id", "first_name", "email"]
