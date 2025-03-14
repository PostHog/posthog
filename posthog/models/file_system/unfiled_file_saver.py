# posthog/models/file_system/unfiled_file_saver.py

from typing import Optional

from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.file_system.file_system import FileSystem, split_path, escape_path
from posthog.models.file_system.file_system_dsl import FILE_SYSTEM_CONFIG


class UnfiledFileSaver:
    """
    Finds & saves FileSystem rows for domain objects that haven't yet been
    represented in the FileSystem, according to the DSL config.
    """

    def __init__(self, team: Team, user: User):
        self.team = team
        self.user = user
        self._in_memory_paths: set[str] = set()

    def save_unfiled_items_by_type(self, file_type: str) -> list[FileSystem]:
        """
        Look up the DSL config to find unfiled items and create a new FileSystem row for each.
        """
        # If the file_type isn't in the DSL, do nothing
        if file_type not in FILE_SYSTEM_CONFIG:
            return []

        config = FILE_SYSTEM_CONFIG[file_type]
        # 1) Query for unfiled items
        queryset = config.get_unfiled_queryset(self.team)

        new_files = []
        for obj in queryset:
            # 2) Build a unique path
            base_folder = config.base_folder
            name = config.get_name(obj)
            path = self._generate_unique_path(base_folder, name)

            # 3) Construct the new FileSystem row
            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type=config.file_type,
                    ref=config.get_ref(obj),
                    href=config.get_href(obj),
                    meta=config.get_meta(obj),
                    created_by=self.user,
                )
            )

        # 4) Bulk create
        FileSystem.objects.bulk_create(new_files)
        return new_files

    def _generate_unique_path(self, base_folder: str, name: str) -> str:
        """
        Local helper: generate a path that doesn't collide with existing DB entries
        or what we've already allocated in-memory during this run.
        """
        desired = f"{base_folder}/{escape_path(name)}"
        path = desired
        index = 1

        while (path in self._in_memory_paths) or (FileSystem.objects.filter(team=self.team, path=path).exists()):
            path = f"{desired} ({index})"
            index += 1

        self._in_memory_paths.add(path)
        return path

    def save_all_unfiled(self) -> list[FileSystem]:
        """
        Convenience method: run `save_unfiled_items_by_type` for all known types.
        """
        created: list[FileSystem] = []
        for file_type in FILE_SYSTEM_CONFIG.keys():
            created.extend(self.save_unfiled_items_by_type(file_type))
        return created


def save_unfiled_files(team: Team, user: User, file_type: Optional[str] = None) -> list[FileSystem]:
    """
    Public helper:
      - If file_type is None, saves unfiled items for ALL known DSL types.
      - Otherwise just for the specified file_type (if recognized).
    """
    saver = UnfiledFileSaver(team, user)
    if file_type is None:
        return saver.save_all_unfiled()
    else:
        return saver.save_unfiled_items_by_type(file_type)
