# posthog/models/file_system/unfiled_file_saver.py

from typing import Optional

from posthog.models.action.action import Action
from posthog.models.team import Team
from posthog.models.user import User
from posthog.models.file_system.file_system import FileSystem, split_path, escape_path
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin

from posthog.models.feature_flag import FeatureFlag
from posthog.models.experiment import Experiment
from posthog.models.insight import Insight
from posthog.models.dashboard import Dashboard
from posthog.models.notebook import Notebook
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

MIXIN_MODELS = {
    "action": Action,
    "feature_flag": FeatureFlag,
    "experiment": Experiment,
    "insight": Insight,
    "dashboard": Dashboard,
    "notebook": Notebook,
    "replay_playlist": SessionRecordingPlaylist,
}


class UnfiledFileSaver:
    """
    Checks each model's get_file_system_unfiled(...) for items that
    haven't been put into FileSystem. Creates them with unique paths.
    """

    def __init__(self, team: Team, user: User):
        self.team = team
        self.user = user
        self._in_memory_paths: set[str] = set()

    def save_unfiled_for_model(self, model_cls: type[FileSystemSyncMixin]) -> list[FileSystem]:
        unfiled_qs = model_cls.get_file_system_unfiled(self.team)
        new_files: list[FileSystem] = []
        for obj in unfiled_qs:
            rep = obj.get_file_system_representation()

            # If should_delete is True, skip making a new entry
            if rep.should_delete:
                continue

            path = self._generate_unique_path(rep.base_folder, rep.name)
            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type=rep.type,
                    ref=rep.ref,
                    href=rep.href,
                    meta=rep.meta,
                    created_by=self.user,
                )
            )
        FileSystem.objects.bulk_create(new_files)
        return new_files

    def _generate_unique_path(self, base_folder: str, name: str) -> str:
        desired = f"{base_folder}/{escape_path(name)}"
        path = desired
        index = 1
        while path in self._in_memory_paths or FileSystem.objects.filter(team=self.team, path=path).exists():
            path = f"{desired} ({index})"
            index += 1
        self._in_memory_paths.add(path)
        return path

    def save_all_unfiled(self) -> list[FileSystem]:
        created_all = []
        for model_cls in MIXIN_MODELS.values():
            created_all.extend(self.save_unfiled_for_model(model_cls))  # type: ignore
        return created_all


def save_unfiled_files(team: Team, user: User, file_type: Optional[str] = None) -> list[FileSystem]:
    saver = UnfiledFileSaver(team, user)
    if file_type is None:
        return saver.save_all_unfiled()

    found_cls = MIXIN_MODELS.get(file_type)
    if not found_cls:
        return []
    return saver.save_unfiled_for_model(found_cls)  # type: ignore
