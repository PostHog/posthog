# posthog/models/file_system/file_system_dsl.py

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING
from collections.abc import Callable
from django.db.models import QuerySet

# We only import model classes for type hints under TYPE_CHECKING to avoid circular references:
if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.feature_flag import FeatureFlag
    from posthog.models.experiment import Experiment
    from posthog.models.insight import Insight
    from posthog.models.dashboard import Dashboard
    from posthog.models.notebook import Notebook


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
    get_unfiled_queryset: Callable[["Team"], QuerySet[Any]] = field(default=lambda team: QuerySet())


#
# Helper functions that perform model imports inline.
# Each returns a QuerySet of "unfiled" items for the given Team.
#


def _feature_flag_unfiled_queryset(team: "Team") -> QuerySet["FeatureFlag"]:
    from django.db.models import Exists, OuterRef, CharField
    from django.db.models.functions import Cast
    from posthog.models.feature_flag import FeatureFlag
    from posthog.models.file_system.file_system import FileSystem

    return (
        FeatureFlag.objects.filter(team=team, deleted=False)
        .annotate(ref_id=Cast("id", output_field=CharField()))
        .annotate(
            already_saved=Exists(FileSystem.objects.filter(team=team, type="feature_flag", ref=OuterRef("ref_id")))
        )
        .filter(already_saved=False)
    )


def _experiment_unfiled_queryset(team: "Team") -> QuerySet["Experiment"]:
    from django.db.models import Exists, OuterRef, CharField
    from django.db.models.functions import Cast
    from posthog.models.experiment import Experiment
    from posthog.models.file_system.file_system import FileSystem

    return (
        Experiment.objects.filter(team=team)
        .annotate(ref_id=Cast("id", output_field=CharField()))
        .annotate(already_saved=Exists(FileSystem.objects.filter(team=team, type="experiment", ref=OuterRef("ref_id"))))
        .filter(already_saved=False)
    )


def _insight_unfiled_queryset(team: "Team") -> QuerySet["Insight"]:
    from django.db.models import Exists, OuterRef, CharField
    from django.db.models.functions import Cast
    from posthog.models.insight import Insight
    from posthog.models.file_system.file_system import FileSystem

    return (
        Insight.objects.filter(team=team, deleted=False, saved=True)
        .annotate(ref_id=Cast("short_id", output_field=CharField()))
        .annotate(already_saved=Exists(FileSystem.objects.filter(team=team, type="insight", ref=OuterRef("ref_id"))))
        .filter(already_saved=False)
    )


def _dashboard_unfiled_queryset(team: "Team") -> QuerySet["Dashboard"]:
    from django.db.models import Exists, OuterRef, CharField
    from django.db.models.functions import Cast
    from posthog.models.dashboard import Dashboard
    from posthog.models.file_system.file_system import FileSystem

    return (
        Dashboard.objects.filter(team=team, deleted=False)
        .exclude(creation_mode="template")
        .annotate(ref_id=Cast("id", output_field=CharField()))
        .annotate(already_saved=Exists(FileSystem.objects.filter(team=team, type="dashboard", ref=OuterRef("ref_id"))))
        .filter(already_saved=False)
    )


def _notebook_unfiled_queryset(team: "Team") -> QuerySet["Notebook"]:
    from django.db.models import Exists, OuterRef, CharField
    from django.db.models.functions import Cast
    from posthog.models.notebook import Notebook
    from posthog.models.file_system.file_system import FileSystem

    return (
        Notebook.objects.filter(team=team, deleted=False)
        .annotate(ref_id=Cast("id", output_field=CharField()))
        .annotate(already_saved=Exists(FileSystem.objects.filter(team=team, type="notebook", ref=OuterRef("ref_id"))))
        .filter(already_saved=False)
    )


#
# Finally, build the FILE_SYSTEM_CONFIG dict referencing these helpers.
#
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
        get_unfiled_queryset=_feature_flag_unfiled_queryset,
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
        get_unfiled_queryset=_experiment_unfiled_queryset,
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
        get_unfiled_queryset=_insight_unfiled_queryset,
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
        get_unfiled_queryset=_dashboard_unfiled_queryset,
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
        get_unfiled_queryset=_notebook_unfiled_queryset,
    ),
}
