"""
DRF serializers for the agent_stack authoring API.

Two model serializers (Application, Revision) + a few request-body serializers
for non-CRUD actions (set_env, promote). Bundle-upload + presigned-URL flow is
deferred to the eventual MCP redesign (see TODO B5 in agent-shared).
"""

from __future__ import annotations

from rest_framework import serializers

from .models import AgentApplication, AgentRevision


class AgentApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentApplication
        fields = [
            "id",
            "team",
            "name",
            "slug",
            "description",
            "live_revision",
            "archived",
            "archived_at",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # encrypted_env is set/cleared via the dedicated `set_env` action;
        # never round-tripped through the standard CRUD payload.
        read_only_fields = ["id", "team", "live_revision", "archived_at", "created_by", "created_at", "updated_at"]


class AgentRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentRevision
        fields = [
            "id",
            "application",
            "parent_revision",
            "state",
            "bundle_uri",
            "bundle_sha256",
            "spec",
            "created_by",
            "created_at",
            "updated_at",
        ]
        # state transitions happen through promote / archive actions; spec is
        # mutable only while state='draft' (enforced in the view).
        read_only_fields = [
            "id",
            "application",
            "state",
            "bundle_sha256",
            "created_by",
            "created_at",
            "updated_at",
        ]


class SetEnvRequestSerializer(serializers.Serializer):
    """Body shape for AgentApplicationViewSet.set_env.

    `env` is a JSON object of string→string. The view encrypts it via the
    same Fernet schedule the worker uses to decrypt.
    """

    env = serializers.DictField(child=serializers.CharField(allow_blank=True), allow_empty=True)


class PromoteRevisionRequestSerializer(serializers.Serializer):
    """Body shape for AgentRevisionViewSet.promote.

    Empty today — promote takes the calling revision's id from the URL and
    flips it `ready → live`, updating the parent application's
    `live_revision`. Left as a body-bearing endpoint so we can add fields
    later (rollback target, audit comment) without changing the URL shape.
    """
