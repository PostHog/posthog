# posthog/models/file_system/file_system_mixin.py

import dataclasses
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import models
from typing import TYPE_CHECKING, Any
from django.db.models import QuerySet
import posthoganalytics

if TYPE_CHECKING:
    from posthog.models.team import Team
from posthog.models.file_system.file_system_representation import FileSystemRepresentation


class FileSystemSyncMixin(models.Model):
    """
    Mixin that:
      - Defines signals to auto-create/update/delete a FileSystem entry on save/delete.
      - Provides a shared `_filter_unfiled_queryset` to exclude items already in FileSystem
        (so models don't import FileSystem themselves).
    """

    class Meta:
        abstract = True

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet[Any]:
        """
        Models override this to return a queryset of items that do not yet have a FileSystem entry.
        Typically calls `_filter_unfiled_queryset(base_qs, team, ref_field)`.
        """
        raise NotImplementedError()

    def get_file_system_representation(self) -> FileSystemRepresentation:
        """
        Returns a FileSystemRepresentation with base_folder, ref, name, href, meta, should_delete.
        """
        raise NotImplementedError()

    @classmethod
    def _filter_unfiled_queryset(cls, qs: QuerySet, team: "Team", type: str, ref_field: str) -> QuerySet:
        """
        Given a base queryset `qs`, annotate a 'ref_id' from `ref_field`,
        then exclude rows that are already saved to FileSystem for (team, file_type).
        """
        from django.db.models import Exists, OuterRef, CharField
        from django.db.models.functions import Cast
        from django.db.models import F
        from posthog.models.file_system.file_system import FileSystem

        # Annotate a 'ref_id' from the chosen model field (e.g. 'id', 'short_id')
        annotated_qs = qs.annotate(ref_id=Cast(F(ref_field), output_field=CharField())).annotate(
            already_saved=Exists(FileSystem.objects.filter(team=team, type=type, ref=OuterRef("ref_id")))
        )
        return annotated_qs.filter(already_saved=False)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        @receiver(post_save, sender=cls)
        def _file_system_post_save(sender, instance: FileSystemSyncMixin, created, **kwargs):
            from posthog.models.file_system.file_system import create_or_update_file, delete_file

            try:
                fs_data = instance.get_file_system_representation()
                if fs_data.should_delete:
                    delete_file(team=instance.team, file_type=fs_data.type, ref=fs_data.ref)
                else:
                    create_or_update_file(
                        team=instance.team,
                        base_folder=fs_data.base_folder,
                        name=fs_data.name,
                        file_type=fs_data.type,
                        ref=fs_data.ref,
                        href=fs_data.href,
                        meta=fs_data.meta,
                        created_by=getattr(instance, "created_by", None),
                    )
            except Exception as e:
                # Don't raise exceptions in signals
                posthoganalytics.capture_exception(e, properties=dataclasses.asdict(fs_data))

        @receiver(post_delete, sender=cls)
        def _file_system_post_delete(sender, instance: FileSystemSyncMixin, **kwargs):
            from posthog.models.file_system.file_system import delete_file

            try:
                fs_data = instance.get_file_system_representation()
                delete_file(team=instance.team, file_type=fs_data.type, ref=fs_data.ref)
            except Exception as e:
                # Don't raise exceptions in signals
                posthoganalytics.capture_exception(e, properties=dataclasses.asdict(fs_data))
