# posthog/models/file_system/file_system_mixin.py

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from typing import Optional


class FileSystemSyncMixin:
    """
    Mixin that automatically registers signals to keep a model in sync
    with the FileSystem, using DSL config from FILE_SYSTEM_CONFIG (dataclass-based).
    """

    # Child classes must specify which config key in FILE_SYSTEM_CONFIG to use.
    file_system_config_key: Optional[str] = None

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not cls.file_system_config_key:
            # If the subclass doesn't set this, do nothing.
            return

        # Import inside the method to avoid circular imports
        from posthog.models.file_system.file_system_dsl import FILE_SYSTEM_CONFIG, FileSystemEntryConfig

        # Retrieve the DSL config (a FileSystemEntryConfig object)
        config: FileSystemEntryConfig = FILE_SYSTEM_CONFIG[cls.file_system_config_key]

        # --- POST_SAVE ---
        @receiver(post_save, sender=cls)
        def _file_system_post_save(sender, instance, created, **kwargs):
            from posthog.models.file_system.file_system import create_or_update_file, delete_file

            # Decide if we should delete or create/update
            if config.should_delete(instance):
                delete_file(
                    team=instance.team,
                    file_type=config.file_type,
                    ref=config.get_ref(instance),
                )
            else:
                create_or_update_file(
                    team=instance.team,
                    base_folder=config.base_folder,
                    name=config.get_name(instance),
                    file_type=config.file_type,
                    ref=config.get_ref(instance),
                    href=config.get_href(instance),
                    meta=config.get_meta(instance),
                    created_by=getattr(instance, "created_by", None),
                )

        # --- POST_DELETE ---
        @receiver(post_delete, sender=cls)
        def _file_system_post_delete(sender, instance, **kwargs):
            from posthog.models.file_system.file_system import delete_file

            delete_file(
                team=instance.team,
                file_type=config.file_type,
                ref=config.get_ref(instance),
            )
