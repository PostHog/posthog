import posthoganalytics
from django.contrib.auth import login
from django.db import transaction
from rest_framework import generics, permissions, serializers

from posthog.api.user import UserSerializer
from posthog.models import Team, User
from posthog.models.user import EE_MISSING, REALM


class TeamSignupSerializer(serializers.Serializer):
    first_name: serializers.Field = serializers.CharField(max_length=128)
    email: serializers.Field = serializers.EmailField()
    password: serializers.Field = serializers.CharField()
    company_name: serializers.Field = serializers.CharField(
        max_length=128, required=False,
    )
    email_opt_in: serializers.Field = serializers.BooleanField(default=True)

    def create(self, validated_data):
        company_name = validated_data.pop("company_name", "")
        is_first_user: bool = not User.objects.exists()

        with transaction.atomic():
            user = User.objects.create_user(**validated_data)
            Team.objects.create_with_data(users=[user], name=company_name)

        login(
            self.context["request"], user, backend="django.contrib.auth.backends.ModelBackend",
        )

        posthoganalytics.capture(
            user.distinct_id, "user signed up", properties={"is_first_user": is_first_user, "is_team_first_user": True},
        )

        posthoganalytics.identify(
            user.distinct_id, properties={"email": user.email, "realm": REALM, "ee_available": not EE_MISSING},
        )

        return user

    def to_representation(self, instance):
        serializer = UserSerializer(instance=instance)
        return serializer.data


class TeamSignupViewset(generics.CreateAPIView):
    serializer_class = TeamSignupSerializer
    permission_classes = (permissions.AllowAny,)
