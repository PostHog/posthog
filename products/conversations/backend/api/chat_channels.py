from __future__ import annotations

from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef, QuerySet

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.permissions import APIScopePermission

from products.conversations.backend.models import ChatChannel, ChatChannelMembership


class ChatChannelMemberSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="user.id", read_only=True, help_text="User ID")
    first_name = serializers.CharField(source="user.first_name", read_only=True, help_text="First name")
    last_name = serializers.CharField(source="user.last_name", read_only=True, help_text="Last name")
    email = serializers.EmailField(source="user.email", read_only=True, help_text="Email address")
    joined_at = serializers.DateTimeField(read_only=True, help_text="When the user joined the channel")


class ChatChannelSerializer(serializers.ModelSerializer):
    member_count = serializers.IntegerField(read_only=True, help_text="Number of members in the channel")
    is_member = serializers.BooleanField(read_only=True, help_text="Whether the requesting user is a member")

    class Meta:
        model = ChatChannel
        fields = [
            "id",
            "name",
            "description",
            "is_default",
            "member_count",
            "is_member",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "is_default", "created_by", "created_at", "updated_at"]

    def validate_name(self, value: str) -> str:
        value = value.strip().lower().replace(" ", "-")
        if not value:
            raise serializers.ValidationError("Channel name cannot be empty.")
        return value


class ChatChannelViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ChatChannel.objects.all()
    permission_classes = [IsAuthenticated, APIScopePermission]
    serializer_class = ChatChannelSerializer

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        user = self.request.user
        return (
            queryset.filter(team=self.team)
            .annotate(
                member_count=Count("memberships"),
                is_member=Exists(ChatChannelMembership.objects.filter(channel=OuterRef("pk"), user=user)),
            )
            .order_by("-is_default", "name")
        )

    def _ensure_default_channel(self) -> None:
        """Lazily create the #general channel and ensure the requesting user is a member."""
        channel = ChatChannel.objects.filter(team=self.team, name="general").first()
        if channel is None:
            try:
                channel = ChatChannel.objects.create(
                    team=self.team,
                    name="general",
                    is_default=True,
                    description="General discussion",
                )
            except IntegrityError:
                channel = ChatChannel.objects.filter(team=self.team, name="general").first()
                if channel is None:
                    return
        ChatChannelMembership.objects.filter(channel=channel, user=self.request.user).first() or (
            self._safe_create_membership(channel)
        )

    def _safe_create_membership(self, channel: ChatChannel) -> None:
        try:
            ChatChannelMembership.objects.create(channel=channel, user=self.request.user)
        except IntegrityError:
            pass

    @extend_schema(
        summary="List chat channels",
        description="Returns all channels for the team. Auto-creates #general on first call.",
        responses={200: ChatChannelSerializer(many=True)},
    )
    def list(self, request: ..., *args: ..., **kwargs: ...) -> Response:
        self._ensure_default_channel()
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer: ChatChannelSerializer) -> None:
        channel = serializer.save(team=self.team, created_by=self.request.user)
        ChatChannelMembership.objects.create(channel=channel, user=self.request.user)

    def perform_destroy(self, instance: ChatChannel) -> None:
        instance.delete()

    @extend_schema(
        summary="Join a channel",
        description="Add the requesting user as a member of this channel.",
        request=None,
        responses={200: ChatChannelSerializer},
    )
    @action(detail=True, methods=["post"], url_path="join")
    def join(self, request: ..., *args: ..., **kwargs: ...) -> Response:
        channel = self.get_object()
        try:
            ChatChannelMembership.objects.create(channel=channel, user=request.user)
        except IntegrityError:
            pass  # already a member
        channel = self.get_object()  # re-fetch for fresh annotations
        serializer = self.get_serializer(channel)
        return Response(serializer.data)

    @extend_schema(
        summary="Leave a channel",
        description="Remove the requesting user from this channel. Cannot leave the default channel.",
        request=None,
        responses={200: ChatChannelSerializer},
    )
    @action(detail=True, methods=["post"], url_path="leave")
    def leave(self, request: ..., *args: ..., **kwargs: ...) -> Response:
        channel = self.get_object()
        ChatChannelMembership.objects.filter(channel=channel, user=request.user).delete()
        channel = self.get_object()  # re-fetch for fresh annotations
        serializer = self.get_serializer(channel)
        return Response(serializer.data)

    @extend_schema(
        summary="List channel members",
        description="Returns all members of this channel.",
        responses={200: ChatChannelMemberSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], url_path="members")
    def members(self, request: ..., *args: ..., **kwargs: ...) -> Response:
        channel = self.get_object()
        memberships = channel.memberships.select_related("user").order_by("joined_at")
        serializer = ChatChannelMemberSerializer(memberships, many=True)
        return Response(serializer.data)
