# posthog/models/file_system/unfiled_file_saver.py
from datetime import datetime
from typing import Optional

from django.utils import timezone

from posthog.models.action.action import Action
from posthog.models.cohort import Cohort
from posthog.models.dashboard import Dashboard
from posthog.models.experiment import Experiment
from posthog.models.feature_flag import FeatureFlag
from posthog.models.file_system.file_system import FileSystem, escape_path, split_path
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.hog_functions.hog_function import HogFunction
from posthog.models.insight import Insight
from posthog.models.link import Link
from posthog.models.notebook import Notebook
from posthog.models.surveys.survey import Survey
from posthog.models.team import Team
from posthog.models.user import User
from posthog.session_recordings.models.session_recording_playlist import SessionRecordingPlaylist

from products.early_access_features.backend.models import EarlyAccessFeature

MIXIN_MODELS = {
    "action": Action,
    "feature_flag": FeatureFlag,
    "experiment": Experiment,
    "insight": Insight,
    "dashboard": Dashboard,
    "link": Link,
    "notebook": Notebook,
    "early_access_feature": EarlyAccessFeature,
    "session_recording_playlist": SessionRecordingPlaylist,
    "cohort": Cohort,
    "hog_function": HogFunction,
    "survey": Survey,
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
        users_by_id: dict[int, User] = {}
        for obj in unfiled_qs:
            rep = obj.get_file_system_representation()

            # If should_delete is True, skip making a new entry
            if rep.should_delete:
                continue

            path = f"{rep.base_folder}/{escape_path(rep.name)}"
            user: User | None = None
            if rep.meta.get("created_by"):
                user = users_by_id.get(rep.meta["created_by"])
                if user is None:
                    user = User.objects.filter(pk=rep.meta["created_by"]).first()
                    if user:
                        users_by_id[rep.meta["created_by"]] = user
                if user is None:
                    user = self.user
            created_at = timezone.now()
            if rep.meta.get("created_at"):
                created_at = datetime.fromisoformat(rep.meta["created_at"])
            new_files.append(
                FileSystem(
                    team=self.team,
                    path=path,
                    depth=len(split_path(path)),
                    type=rep.type,
                    ref=rep.ref,
                    href=rep.href,
                    meta=rep.meta,
                    created_by=user,
                    created_at=created_at,
                    shortcut=False,
                )
            )
        FileSystem.objects.bulk_create(new_files)
        return new_files

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
