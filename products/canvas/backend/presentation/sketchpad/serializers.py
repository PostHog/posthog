from __future__ import annotations

from typing import Any, Protocol, cast

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.models.user import User

from products.canvas.backend.facade.enums import SketchpadActorKind
from products.canvas.backend.models import Sketchpad, SketchpadOp
from products.canvas.backend.sketchpad.records import JsonValue, SketchpadRecordAnnotations, hydrate_ops, op_sources
from products.canvas.backend.sketchpad.schema import (
    MAX_SKETCHPAD_OP_BYTES,
    OP_SCHEMA,
    READ_OP_SCHEMA,
    READ_SNAPSHOT_SCHEMA,
    SNAPSHOT_SCHEMA,
    validate_op,
)

MAX_PREVIEW_BOXES = 24


class SketchpadPreviewAnnotations(Protocol):
    preview_fragments: list[dict[str, float]]


def sketchpad_actor_person(user: User | None, user_id: int | None = None) -> dict[str, Any]:
    if user is None:
        return {"user_id": user_id, "user_uuid": None, "user_name": None, "user_email": None}
    return {
        "user_id": user.pk,
        "user_uuid": str(user.uuid),
        "user_name": user.first_name or user.email,
        "user_email": user.email,
    }


@extend_schema_field(OP_SCHEMA, component_name="SketchpadOperation")
class SketchpadOpField(serializers.JSONField):
    default_validators = [validate_op]


@extend_schema_field(READ_OP_SCHEMA, component_name="SketchpadReadOperation")
class SketchpadReadOpField(SketchpadOpField):
    pass


@extend_schema_field(READ_SNAPSHOT_SCHEMA, component_name="SketchpadReadSnapshot")
class SketchpadReadSnapshotField(serializers.JSONField):
    pass


@extend_schema_field(SNAPSHOT_SCHEMA, component_name="SketchpadSnapshot")
class SketchpadSnapshotField(serializers.JSONField):
    pass


class SketchpadCreatorSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=SketchpadActorKind.choices, help_text="Always user for a creator.")
    user_id = serializers.IntegerField(allow_null=True, help_text="Id of the user, or null when the account is gone.")
    user_name = serializers.CharField(allow_null=True, help_text="First name of the user, else their email.")
    user_uuid = serializers.UUIDField(allow_null=True, help_text="Uuid of the user, for a stable avatar color.")
    user_email = serializers.CharField(allow_null=True, help_text="Email of the user, for a Gravatar.")


class SketchpadActorSerializer(SketchpadCreatorSerializer):
    task_id = serializers.UUIDField(allow_null=True, help_text="Id of the agent task that made the change, or null.")


class SketchpadLogEntryListSerializer(serializers.ListSerializer):
    def to_representation(self, data: Any) -> list[Any]:
        rows = list(data)
        hydrate_ops(rows)
        return cast(list[Any], super().to_representation(rows))


class SketchpadLogEntrySerializer(serializers.Serializer):
    seq = serializers.IntegerField(read_only=True, help_text="Position in the sketchpad's log, starting at 1.")
    op_id = serializers.CharField(read_only=True, help_text="Id the client chose for the op.")
    actor = serializers.SerializerMethodField(help_text="Who recorded the op.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the server recorded the op.")
    op: SketchpadOpField = SketchpadReadOpField(read_only=True, help_text="The op with fragment source references.")

    @extend_schema_field(SketchpadActorSerializer)
    def get_actor(self, entry: SketchpadOp) -> dict[str, Any]:
        return {
            "kind": entry.actor_kind,
            **sketchpad_actor_person(entry.actor_user, entry.actor_user_id),
            "task_id": str(entry.actor_task_id) if entry.actor_task_id else None,
        }


class SketchpadPreviewBoxSerializer(serializers.Serializer):
    x = serializers.FloatField(read_only=True, help_text="Left edge of the fragment, in world units.")
    y = serializers.FloatField(read_only=True, help_text="Top edge of the fragment, in world units.")
    w = serializers.FloatField(read_only=True, help_text="Width of the fragment, in world units.")
    h = serializers.FloatField(read_only=True, help_text="Height of the fragment, in world units.")


class SketchpadSummaryListSerializer(serializers.ListSerializer):
    def to_representation(self, data: Any) -> list[Any]:
        rows = list(data)
        ids = {getattr(row, "last_actor_user_id", None) for row in rows}
        ids.discard(None)
        self.context["last_actor_users"] = {user.pk: user for user in User.objects.filter(pk__in=ids)} if ids else {}
        return cast(list[Any], super().to_representation(rows))


class SketchpadBaseSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Id of the sketchpad.")
    name = serializers.CharField(read_only=True, help_text="Display name of the sketchpad.")
    channel = serializers.UUIDField(
        source="channel_id", read_only=True, help_text="Id of the space the sketchpad is filed in."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the sketchpad was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the sketchpad or its log last changed.")
    head_seq = serializers.IntegerField(read_only=True, help_text="Seq of the newest op in the sketchpad's log.")
    pinned = serializers.SerializerMethodField(help_text="True while the sketchpad is pinned to the top of its space.")
    created_by = serializers.SerializerMethodField(help_text="Who created the sketchpad, or null.")

    @extend_schema_field(serializers.BooleanField())
    def get_pinned(self, sketchpad: Sketchpad) -> bool:
        return sketchpad.pinned_at is not None

    @extend_schema_field(SketchpadCreatorSerializer(allow_null=True))
    def get_created_by(self, sketchpad: Sketchpad) -> dict[str, Any] | None:
        if sketchpad.created_by_id is None:
            return None
        return {
            "kind": SketchpadActorKind.USER,
            **sketchpad_actor_person(sketchpad.created_by, sketchpad.created_by_id),
        }


class SketchpadSummarySerializer(SketchpadBaseSerializer):
    class Meta:
        list_serializer_class = SketchpadSummaryListSerializer

    last_actor = serializers.SerializerMethodField(
        help_text="Who recorded the newest op, or the creator when the sketchpad has no ops."
    )
    fragment_count = serializers.IntegerField(read_only=True, help_text="Number of fragments in the stored snapshot.")
    preview = serializers.SerializerMethodField(
        help_text="Boxes of the first fragments, so a list can draw the shape of the sketchpad. At most 24."
    )

    @extend_schema_field(SketchpadCreatorSerializer(allow_null=True))
    def get_last_actor(self, sketchpad: Sketchpad) -> dict[str, Any] | None:
        user_id = getattr(sketchpad, "last_actor_user_id", None)
        if user_id is None:
            return self.get_created_by(sketchpad)
        users = self.context.get("last_actor_users") or {}
        return {
            "kind": getattr(sketchpad, "last_actor_kind", None) or SketchpadActorKind.USER,
            **sketchpad_actor_person(users.get(user_id), user_id),
        }

    @extend_schema_field(SketchpadPreviewBoxSerializer(many=True))
    def get_preview(self, sketchpad: SketchpadPreviewAnnotations) -> list[dict[str, float]]:
        return [{key: float(fragment[key]) for key in ("x", "y", "w", "h")} for fragment in sketchpad.preview_fragments]


class SketchpadSerializer(SketchpadBaseSerializer):
    history_start_seq = serializers.IntegerField(read_only=True, help_text="Seq represented by history_snapshot.")
    history_snapshot = SketchpadSnapshotField(
        read_only=True, help_text="Board state before the retained operation log."
    )
    snapshot = SketchpadReadSnapshotField(
        read_only=True, help_text="Current sketchpad. Resolve fragment codeRef values through source_versions."
    )
    source_versions = serializers.DictField(
        child=serializers.CharField(), read_only=True, help_text="Source text by SHA-256 hash."
    )

    def to_representation(self, instance: SketchpadRecordAnnotations) -> dict[str, Any]:
        result = cast(dict[str, Any], super().to_representation(instance))
        result["source_versions"] = {item["key"]: item["value"] for item in instance.record_sources}
        result["snapshot"] = {
            "schemaVersion": 1,
            "fragments": instance.record_fragments,
            "state": {item["key"]: item["value"] for item in instance.record_state},
        }
        return result


class SketchpadCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, help_text="Display name of the sketchpad.")
    channel_id = serializers.UUIDField(help_text="Id of the space the sketchpad belongs to.")


class SketchpadWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False, help_text="Display name of the sketchpad.")
    channel_id = serializers.UUIDField(required=False, help_text="Id of the space the sketchpad belongs to.")
    pinned = serializers.BooleanField(required=False, help_text="Pin the sketchpad to the top of its space.")


class SketchpadCompileSerializer(serializers.Serializer):
    refs = serializers.ListField(
        child=serializers.RegexField(r"^[0-9a-f]{64}$"),
        max_length=256,
        allow_empty=False,
        help_text="Source hashes from this sketchpad. Missing results are still being compiled.",
    )


class SketchpadCompiledFragmentSerializer(serializers.Serializer):
    code = serializers.CharField(allow_blank=True, help_text="Compiled JavaScript without shared libraries.")
    imports = serializers.ListField(child=serializers.CharField(), help_text="Required shared library names.")
    error = serializers.CharField(allow_null=True, help_text="Compilation error, or null on success.")


class SketchpadCompiledResponseSerializer(serializers.Serializer):
    results = serializers.DictField(
        child=SketchpadCompiledFragmentSerializer(), help_text="Available compiled results, keyed by source hash."
    )


class SketchpadOpsQuerySerializer(serializers.Serializer):
    since = serializers.IntegerField(
        required=False, default=0, min_value=0, help_text="Return ops with seq greater than this. Defaults to 0."
    )
    limit = serializers.IntegerField(
        required=False, default=500, min_value=1, max_value=1000, help_text="Page size, at most 1000. Defaults to 500."
    )


class SketchpadHydratedLogEntrySerializer(SketchpadLogEntrySerializer):
    op = SketchpadOpField(read_only=True, help_text="The op with fragment source text.")

    class Meta:
        list_serializer_class = SketchpadLogEntryListSerializer


class SketchpadOpsPageSerializer(serializers.Serializer):
    results = SketchpadLogEntrySerializer(many=True, help_text="Ops in ascending seq order.")
    head_seq = serializers.IntegerField(help_text="Seq of the newest op in the sketchpad's log.")
    history_start_seq = serializers.IntegerField(help_text="Seq represented by history_snapshot.")
    history_snapshot = SketchpadSnapshotField(help_text="Board state before the retained operation log.")
    source_versions = serializers.SerializerMethodField(
        help_text="Fragment source text keyed by SHA-256, once per page."
    )

    @extend_schema_field(serializers.DictField(child=serializers.CharField()))
    def get_source_versions(self, instance: dict[str, Any]) -> dict[str, JsonValue]:
        return op_sources(instance["results"])


class SketchpadActorInputSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(
        choices=SketchpadActorKind.choices, help_text="user for a direct edit, agent for a change made by an agent."
    )
    task_id = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text="Acting task, if any. Must match the sandbox binding or a task the signed-in user can control.",
    )


class SketchpadOpDraftSerializer(serializers.Serializer):
    op_id = serializers.CharField(
        max_length=64, help_text="Client-chosen id, unique per sketchpad. Resending the same id records nothing new."
    )
    op = SketchpadOpField(
        help_text=f"The op. Restore uses the request size limit; other ops are capped at {MAX_SKETCHPAD_OP_BYTES // 1024} KB."
    )


class SketchpadAppendOpsSerializer(serializers.Serializer):
    base_seq = serializers.IntegerField(
        min_value=0, help_text="Newest server sequence known when the first op was created."
    )
    ops = SketchpadOpDraftSerializer(
        # DRF passes max_length to the ListSerializer that many=True builds, but the stubs
        # type this call against the child serializer, which has no such argument.
        many=True,  # type: ignore[call-arg]
        allow_empty=True,
        max_length=1000,
        help_text="Up to 1000 ops to record, in order. An empty list makes no change.",
    )
    actor = SketchpadActorInputSerializer(help_text="Who is making the change.")


class SketchpadAppendedOpSerializer(serializers.Serializer):
    op_id = serializers.CharField(help_text="The op_id the client sent.")
    seq = serializers.IntegerField(help_text="Seq assigned to the op, or its existing seq when already recorded.")


class SketchpadAppendResultSerializer(serializers.Serializer):
    results = SketchpadAppendedOpSerializer(many=True, help_text="One entry per submitted op, in order.")
    replayed = SketchpadHydratedLogEntrySerializer(
        many=True, help_text="Accepted log entries for repeated operation IDs."
    )
    head_seq = serializers.IntegerField(help_text="Seq of the newest op after this append.")
