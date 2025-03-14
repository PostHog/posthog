# posthog/models/file_system_mixin.py

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


class FileSystemSyncMixin:
    """
    Mixin that automatically registers signals to keep a model in sync
    with the FileSystem, using DSL config from FILE_SYSTEM_CONFIG.
    """

    # Child classes must specify which config key in FILE_SYSTEM_CONFIG to use.
    file_system_config_key: str = None

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not cls.file_system_config_key:
            # If the subclass doesn't set this, do nothing
            return

        from posthog.models.file_system.file_system_dsl import FILE_SYSTEM_CONFIG

        # Retrieve the DSL config
        dsl = FILE_SYSTEM_CONFIG[cls.file_system_config_key]

        # --- POST_SAVE ---
        @receiver(post_save, sender=cls)
        def _file_system_post_save(sender, instance, created, **kwargs):
            from posthog.models.file_system.file_system import create_or_update_file, delete_file

            # If `should_delete` is true, remove the file system entry
            if dsl["should_delete"](instance):
                delete_file(
                    team=instance.team,
                    file_type=dsl["file_type"],
                    ref=dsl["get_ref"](instance),
                )
            else:
                # otherwise, create or update
                create_or_update_file(
                    team=instance.team,
                    base_folder=dsl["base_folder"],
                    name=dsl["get_name"](instance),
                    file_type=dsl["file_type"],
                    ref=dsl["get_ref"](instance),
                    href=dsl["get_href"](instance),
                    meta=dsl["get_meta"](instance),
                    created_by=getattr(instance, "created_by", None),
                )

        # --- POST_DELETE ---
        @receiver(post_delete, sender=cls)
        def _file_system_post_delete(sender, instance, **kwargs):
            from posthog.models.file_system.file_system import delete_file

            # On physical delete, remove from the file system:
            delete_file(
                team=instance.team,
                file_type=dsl["file_type"],
                ref=dsl["get_ref"](instance),
            )
