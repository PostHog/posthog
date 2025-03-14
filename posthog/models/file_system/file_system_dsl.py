FILE_SYSTEM_CONFIG = {
    "feature_flag": {
        "base_folder": "Unfiled/Feature Flags",
        "file_type": "feature_flag",
        "get_ref": lambda instance: str(instance.id),
        "get_name": lambda instance: instance.name or "Untitled",
        "get_href": lambda instance: f"/feature_flags/{instance.id}",
        "get_meta": lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        "should_delete": lambda instance: instance.deleted,
    },
    "experiment": {
        "base_folder": "Unfiled/Experiments",
        "file_type": "experiment",
        "get_ref": lambda instance: str(instance.id),
        "get_name": lambda instance: instance.name or "Untitled",
        "get_href": lambda instance: f"/experiments/{instance.id}",
        "get_meta": lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        "should_delete": lambda instance: False,
    },
    "insight": {
        "base_folder": "Unfiled/Insights",
        "file_type": "insight",
        "get_ref": lambda instance: instance.short_id,
        "get_name": lambda instance: instance.name or "Untitled",
        "get_href": lambda instance: f"/insights/{instance.short_id}",
        "get_meta": lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        "should_delete": lambda instance: instance.deleted or not instance.saved,
    },
    "dashboard": {
        "base_folder": "Unfiled/Dashboards",
        "file_type": "dashboard",
        "get_ref": lambda instance: instance.id,
        "get_name": lambda instance: instance.name or "Untitled",
        "get_href": lambda instance: f"/dashboards/{instance.id}",
        "get_meta": lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        "should_delete": lambda instance: instance.deleted or instance.creation_mode == "template",
    },
    "notebook": {
        "base_folder": "Unfiled/Notebooks",
        "file_type": "notebook",
        "get_ref": lambda instance: instance.id,
        "get_name": lambda instance: instance.title or "Untitled",
        "get_href": lambda instance: f"/notebooks/{instance.id}",
        "get_meta": lambda instance: {
            "created_at": str(getattr(instance, "created_at", "")),
            "created_by": instance.created_by_id,
        },
        "should_delete": lambda instance: instance.deleted,
    },
}
