# posthog/models/file_system/file_system_dsl.py

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable


@dataclass
class FileSystemEntryConfig:
    """
    Defines how a particular "file type" is represented in the FileSystem.
    """

    base_folder: str
    file_type: str
    get_ref: Callable[[Any], str] = field(default=lambda instance: str(instance.id))
    get_name: Callable[[Any], str] = field(default=lambda instance: "Untitled")
    get_href: Callable[[Any], str] = field(default=lambda instance: f"/default/{instance.id}")
    get_meta: Callable[[Any], dict[str, Any]] = field(default=lambda instance: {})
    should_delete: Callable[[Any], bool] = field(default=lambda instance: False)


FILE_SYSTEM_CONFIG: dict[str, FileSystemEntryConfig] = {
    "feature_flag": FileSystemEntryConfig(
        base_folder="Unfiled/Feature Flags",
        file_type="feature_flag",
        get_ref=lambda instance: str(instance.id),
        get_name=lambda instance: instance.name or "Untitled",
        get_href=lambda instance: f"/feature_flags/{instance.id}",
        get_meta=lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        should_delete=lambda instance: instance.deleted,
    ),
    "experiment": FileSystemEntryConfig(
        base_folder="Unfiled/Experiments",
        file_type="experiment",
        get_ref=lambda instance: str(instance.id),
        get_name=lambda instance: instance.name or "Untitled",
        get_href=lambda instance: f"/experiments/{instance.id}",
        get_meta=lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        should_delete=lambda instance: False,
    ),
    "insight": FileSystemEntryConfig(
        base_folder="Unfiled/Insights",
        file_type="insight",
        get_ref=lambda instance: instance.short_id,
        get_name=lambda instance: instance.name or "Untitled",
        get_href=lambda instance: f"/insights/{instance.short_id}",
        get_meta=lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        should_delete=lambda instance: instance.deleted or not instance.saved,
    ),
    "dashboard": FileSystemEntryConfig(
        base_folder="Unfiled/Dashboards",
        file_type="dashboard",
        get_ref=lambda instance: str(instance.id),
        get_name=lambda instance: instance.name or "Untitled",
        get_href=lambda instance: f"/dashboards/{instance.id}",
        get_meta=lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        should_delete=lambda instance: instance.deleted or instance.creation_mode == "template",
    ),
    "notebook": FileSystemEntryConfig(
        base_folder="Unfiled/Notebooks",
        file_type="notebook",
        get_ref=lambda instance: str(instance.id),
        get_name=lambda instance: instance.title or "Untitled",
        get_href=lambda instance: f"/notebooks/{instance.id}",
        get_meta=lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        should_delete=lambda instance: instance.deleted,
    ),
}
