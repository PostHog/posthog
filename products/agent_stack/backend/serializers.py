"""
DRF serializers for the agent_stack authoring API.

Two model serializers (Application, Revision) + a few request-body serializers
for non-CRUD actions (set_env, promote). Bundle-upload + presigned-URL flow is
deferred to the eventual MCP redesign (see TODO B5 in agent-shared).
"""

from __future__ import annotations

from typing import Any

import jsonschema
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import AgentApplication, AgentRevision
from .spec_schema import AGENT_SPEC_JSON_SCHEMA, AGENT_SPEC_JSON_SCHEMA_FOR_WRITE


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


@extend_schema_field(AGENT_SPEC_JSON_SCHEMA)
class AgentSpecField(serializers.JSONField):
    """Spec JSON typed against `AGENT_SPEC_JSON_SCHEMA` so drf-spectacular
    publishes the real shape downstream — generated TS types, MCP tool
    descriptions, and the OpenAPI doc all see real fields instead of an
    opaque `{}`."""


class AgentRevisionSerializer(serializers.ModelSerializer):
    spec = AgentSpecField(required=False, default=dict)

    def validate_spec(self, value: Any) -> Any:
        # Same shape the janitor's `AgentSpecSchema.parse` will reject on
        # read. Catching it here turns a future 500 / process-level surprise
        # into a clean 400 at write time.
        try:
            jsonschema.validate(value, AGENT_SPEC_JSON_SCHEMA_FOR_WRITE)
        except jsonschema.ValidationError as e:
            path = ".".join(str(p) for p in e.absolute_path) or "<root>"
            raise serializers.ValidationError(f"spec.{path}: {e.message}") from e
        return value

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
        extra_kwargs = {
            # The runner / janitor address bundles by revision_id; bundle_uri is
            # the storage-prefix metadata. We default it server-side so MCP
            # callers (and humans) creating a draft don't need to know about it.
            "bundle_uri": {"required": False, "default": ""},
        }


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


class WriteFileRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/file/. `path` lives in the query
    string (matches the janitor wire format); `content` is the new file body."""

    content = serializers.CharField(allow_blank=True, trim_whitespace=False)


class WriteBundleRequestSerializer(serializers.Serializer):
    """Body shape for PUT /revisions/<id>/bundle/ — the bulk upload.

    `files` is a `{path: utf-8 content}` map. `mode='replace'` wipes the
    existing bundle before writing the new set; `'merge'` upserts."""

    files = serializers.DictField(child=serializers.CharField(allow_blank=True, trim_whitespace=False))
    mode = serializers.ChoiceField(choices=["replace", "merge"], default="replace")


class CloneFromRequestSerializer(serializers.Serializer):
    """Body shape for POST /revisions/<id>/clone_from/ — copy every file
    from `source_revision_id` into this (draft) revision."""

    source_revision_id = serializers.UUIDField()


class NewDraftRevisionRequestSerializer(serializers.Serializer):
    """Body shape for POST /revisions/clone_from/ — atomically create a new
    draft revision under `application_id` and clone its initial bundle from
    `source_revision_id`. Convenience for the "edit live" flow so the MCP
    doesn't have to do create-then-clone-from in two calls."""

    application_id = serializers.UUIDField()
    source_revision_id = serializers.UUIDField()
