from typing import Any, Optional

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.file_system.file_system import validate_file_system_path
from posthog.models.activity_logging.activity_log import ActivityScope, Change
from posthog.models.file_system.file_system import folder_of
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin


def move_to_folder_field(noun: str) -> serializers.CharField:
    return serializers.CharField(
        required=False,
        write_only=True,
        validators=[validate_file_system_path],
        help_text=(
            f"Project-tree folder to file this {noun} in, e.g. 'Experiments' or 'Experiments/Growth'. "
            f"Separate nested folders with '/'. Folders that don't exist yet are created. "
            f"The {noun} keeps its own name. "
            f"Returns a 400 error when the {noun} doesn't appear in the project tree."
        ),
    )


@extend_schema_field(serializers.CharField(allow_null=True))
class FolderField(serializers.Field):
    """Reads the `_folder_path` annotation only, so serializing inside another resource never queries."""

    def __init__(self, noun: str) -> None:
        super().__init__(
            source="*",
            read_only=True,
            help_text=(
                f"Project-tree folder this {noun} is filed in, e.g. 'Unfiled/Insights'. An empty string means "
                f"the project root. Null when the {noun} isn't in the project tree, or when this response "
                f"doesn't include it, such as inside another resource."
            ),
        )

    def to_representation(self, value: Any) -> Optional[str]:
        return folder_of(getattr(value, "_folder_path", None))


def file_in_folder_on_create(validated_data: dict) -> Optional[str]:
    """Hand `move_to_folder` to the create-time filing, which writes the entry once with its parent folders."""
    folder = validated_data.pop("move_to_folder", None)
    if folder is not None:
        validated_data["_create_in_folder"] = folder
    return folder


def load_folder_after_create(instance: FileSystemSyncMixin, folder: Optional[str], noun: str) -> None:
    """Loads `folder` for the create response, and rejects a requested folder the item can't be filed in.

    Call inside the create transaction, so a rejected request leaves nothing behind.
    """
    path = instance.file_system_path()
    if folder is not None and path is None:
        raise _not_in_project_tree(noun)
    instance._folder_path = path


def move_to_folder_or_reject(
    instance: FileSystemSyncMixin, folder: str, user_id: Optional[int], noun: str, scope: ActivityScope
) -> Change:
    """Call inside the update transaction. Returns the folder change for the update's activity log entry."""
    move = instance.move_file_system_entry(folder, user_id)
    if move is None:
        raise _not_in_project_tree(noun)
    return Change(type=scope, action="changed", field="folder", before=move.before, after=move.after)


def _not_in_project_tree(noun: str) -> serializers.ValidationError:
    return serializers.ValidationError(
        {"move_to_folder": f"This {noun} doesn't appear in the project tree, so it can't be filed in a folder."}
    )
