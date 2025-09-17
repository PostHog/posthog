import dataclasses
from typing import TYPE_CHECKING, Any, Optional

from django.db.models import CharField, Exists, F, Model, OuterRef, Q, QuerySet
from django.db.models.functions import Cast
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.team import Team
from posthog.models.file_system.file_system_representation import FileSystemRepresentation


class FileSystemSyncMixin(Model):
    """
    Mixin that:
      - Defines signals to auto-create/update/delete a FileSystem entry on save/delete.
      - Provides a shared `_filter_unfiled_queryset` to exclude items already in FileSystem
        (so models don't import FileSystem themselves).
    """

    class Meta:
        abstract = True

    def __init__(self, *args, _create_in_folder: Optional[str] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_in_folder = _create_in_folder

    @classmethod
    def get_file_system_unfiled(cls, team: "Team") -> QuerySet[Any]:
        """
        Models override this to return a queryset of items that do not yet have a FileSystem entry.
        Typically calls `_filter_unfiled_queryset(base_qs, team, ref_field)`.
        """
        raise NotImplementedError()

    def _get_assigned_folder(self, default_folder: str) -> str:
        if isinstance(self._create_in_folder, str):
            return self._create_in_folder
        return default_folder

    def get_file_system_representation(self) -> FileSystemRepresentation:
        """
        Returns a FileSystemRepresentation with base_folder, ref, name, href, meta, should_delete.
        """
        raise NotImplementedError()

    @classmethod
    def _filter_unfiled_queryset(
        cls,
        qs: QuerySet,
        team: "Team",
        ref_field: str,
        type: Optional[str | list[str]] = None,
        type__startswith: Optional[str] = None,
    ) -> QuerySet:
        """
        Given a base queryset `qs`, annotate a 'ref_id' from `ref_field`,
        then exclude rows that are already saved to FileSystem for (team, file_type).
        """
        from posthog.models.file_system.file_system import FileSystem

        if type:
            types = [type] if isinstance(type, str) else type
            already_saved = FileSystem.objects.filter(team=team, type__in=types, ref=OuterRef("ref_id")).filter(
                ~Q(shortcut=True)
            )
        elif type__startswith:
            already_saved = FileSystem.objects.filter(
                team=team, type__startswith=type__startswith, ref=OuterRef("ref_id")
            ).filter(~Q(shortcut=True))
        else:
            raise ValueError("Either 'type' or 'type__startswith' must be provided")

        # Annotate a 'ref_id' from the chosen model field (e.g. 'id', 'short_id')
        annotated_qs = qs.annotate(ref_id=Cast(F(ref_field), output_field=CharField())).annotate(
            already_saved=Exists(already_saved)
        )
        return annotated_qs.filter(already_saved=False)

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        @receiver(post_save, sender=cls, weak=False)
        def _file_system_post_save(sender, instance: FileSystemSyncMixin, created, **kwargs):
            from posthog.models.file_system.file_system import create_or_update_file, delete_file

            fs_data = instance.get_file_system_representation()
            try:
                team = instance.team  # type: ignore
                if fs_data.should_delete:
                    delete_file(team=team, file_type=fs_data.type, ref=fs_data.ref)
                else:
                    create_or_update_file(
                        team=team,
                        base_folder=fs_data.base_folder,
                        name=fs_data.name,
                        file_type=fs_data.type,
                        ref=fs_data.ref,
                        href=fs_data.href,
                        meta=fs_data.meta,
                        created_at=fs_data.meta.get("created_at") or getattr(instance, "created_at", None),
                        created_by_id=fs_data.meta.get("created_by") or getattr(instance, "created_by_id", None),
                    )
            except Exception as e:
                # Don't raise exceptions in signals
                capture_exception(e, additional_properties=dataclasses.asdict(fs_data))

        @receiver(post_delete, sender=cls, weak=False)
        def _file_system_post_delete(sender, instance: FileSystemSyncMixin, **kwargs):
            from posthog.models.file_system.file_system import delete_file

            fs_data = instance.get_file_system_representation()
            try:
                team = instance.team  # type: ignore
                delete_file(team=team, file_type=fs_data.type, ref=fs_data.ref)
            except Exception as e:
                # Don't raise exceptions in signals
                capture_exception(e, additional_properties=dataclasses.asdict(fs_data))
