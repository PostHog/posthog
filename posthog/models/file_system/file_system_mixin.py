import dataclasses
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any, Optional

from django.db import transaction
from django.db.models import CharField, Exists, F, Model, OuterRef, Q, QuerySet
from django.db.models.functions import Cast
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from posthog.exceptions_capture import capture_exception

if TYPE_CHECKING:
    from posthog.models.team import Team
from posthog.models.file_system.constants import DEFAULT_SURFACE, surface_q
from posthog.models.file_system.file_system_representation import FileSystemRepresentation

_file_system_sync_enabled: ContextVar[bool] = ContextVar("file_system_sync_enabled", default=True)


@contextmanager
def file_system_sync(enabled: bool) -> Iterator[None]:
    """Turn the save and delete signals' file row writes off for the saves inside the block.

    A view whose caller may change an object but not its file in the tree saves inside
    `file_system_sync(False)`. The object saves, and its file keeps its name, folder and existence.
    """
    token = _file_system_sync_enabled.set(enabled)
    try:
        yield
    finally:
        _file_system_sync_enabled.reset(token)


class FileSystemSyncMixin(Model):
    """
    Mixin that:
      - Defines signals to auto-create/update/delete a FileSystem entry on save/delete.
      - Provides a shared `_filter_unfiled_queryset` to exclude items already in FileSystem
        (so models don't import FileSystem themselves).
    """

    class Meta:
        abstract = True

    def __init__(self, *args: Any, _create_in_folder: object = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._create_in_folder = _create_in_folder

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        @receiver(post_save, sender=cls, weak=False)
        def _file_system_post_save(sender, instance: "FileSystemSyncMixin", created, **kwargs):
            if _file_system_sync_enabled.get():
                instance.sync_file_system()

        @receiver(post_delete, sender=cls, weak=False)
        def _file_system_post_delete(sender, instance: "FileSystemSyncMixin", **kwargs):
            from posthog.models.file_system.file_system import delete_file
            from posthog.models.team import Team

            if not _file_system_sync_enabled.get():
                return
            fs_data = instance.get_file_system_representation()
            try:
                team = instance.team  # type: ignore
                with transaction.atomic():
                    delete_file(team=team, file_type=fs_data.type, ref=fs_data.ref, surface=fs_data.surface)
            except Team.DoesNotExist:
                # Team was already deleted
                pass
            except Exception as e:
                # Don't raise exceptions in signals
                capture_exception(e, additional_properties=dataclasses.asdict(fs_data))

    def sync_file_system(self) -> None:
        from posthog.models.file_system.file_system import create_or_update_file, delete_file

        fs_data = self.get_file_system_representation()
        try:
            with transaction.atomic():
                team = self.team  # type: ignore
                if fs_data.should_delete:
                    delete_file(team=team, file_type=fs_data.type, ref=fs_data.ref, surface=fs_data.surface)
                elif self.files_new_rows() or self._has_file_system_row(team, fs_data):
                    create_or_update_file(
                        team=team,
                        base_folder=fs_data.base_folder,
                        name=fs_data.name,
                        file_type=fs_data.type,
                        ref=fs_data.ref,
                        href=fs_data.href,
                        meta=fs_data.meta,
                        created_at=fs_data.meta.get("created_at") or getattr(self, "created_at", None),
                        created_by_id=fs_data.meta.get("created_by") or getattr(self, "created_by_id", None),
                        surface=fs_data.surface,
                    )
        except Exception as e:
            # Don't raise exceptions in signals
            capture_exception(e, additional_properties=dataclasses.asdict(fs_data))

    def files_new_rows(self) -> bool:
        return True

    @staticmethod
    def _has_file_system_row(team: "Team", fs_data: FileSystemRepresentation) -> bool:
        from posthog.models.file_system.file_system import FileSystem
        from posthog.models.file_system.refs import file_refs_q

        return FileSystem.objects.filter(
            surface_q(fs_data.surface),
            file_refs_q(fs_data.type, [fs_data.ref]),
            ~Q(shortcut=True),
            team=team,
            type=fs_data.type,
        ).exists()

    @classmethod
    def get_file_system_unfiled(cls, team: "Team", surface: str = DEFAULT_SURFACE) -> QuerySet[Any]:
        """
        Models override this to return a queryset of items that do not yet have a FileSystem entry
        for the given surface. Typically calls `_filter_unfiled_queryset(base_qs, team, ref_field, surface=surface)`.
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
        surface: str = DEFAULT_SURFACE,
    ) -> QuerySet:
        """
        Given a base queryset `qs`, annotate a 'ref_id' from `ref_field`,
        then exclude rows that are already saved to FileSystem for (team, surface, file_type).
        """
        from posthog.models.file_system.file_system import FileSystem
        from posthog.models.file_system.refs import same_file_ref

        if type:
            types = [type] if isinstance(type, str) else type
            already_saved = FileSystem.objects.filter(
                surface_q(surface), same_file_ref(types, "ref", OuterRef("ref_id")), team=team, type__in=types
            ).filter(~Q(shortcut=True))
        elif type__startswith:
            already_saved = FileSystem.objects.filter(
                surface_q(surface), team=team, type__startswith=type__startswith, ref=OuterRef("ref_id")
            ).filter(~Q(shortcut=True))
        else:
            raise ValueError("Either 'type' or 'type__startswith' must be provided")

        # Annotate a 'ref_id' from the chosen model field (e.g. 'id', 'short_id')
        annotated_qs = qs.annotate(ref_id=Cast(F(ref_field), output_field=CharField())).annotate(
            already_saved=Exists(already_saved)
        )
        return annotated_qs.filter(already_saved=False)
